"""Stress test for the Cat Lock rules: random key storms, checked for safety.

Plays millions of random key events (presses, releases, Windows auto-repeat,
modifiers, lock keys, bad shortcuts, time jumps, settings flipped mid-storm,
key-ups that never reach the hook) into a CatFilter, while keeping track of
what Windows itself would see. After every event it checks:

  1. no exceptions;
  2. once a key is physically let go, Windows never still thinks it is held
     (a "stuck key" would be the one really harmful thing this app could do);
  3. the filter's own lists stay small;
and at the end of each storm, with all keys up and a few seconds of quiet:
  4. cat mode has ended and an ordinary letter types again.

Run: python test_stress.py            (100 storms x 20,000 events)
     python test_stress.py 500 50000  (storms, events per storm)
"""
import random
import sys
import time

import catfilter as cf

LETTERS = [ord(c) for c in "ASDFJKLWIXZEPCQ"]
OTHERS = [0x08, 0x0D, 0x20, 0x2D, 0x25, 0x26, 0x70, 0x73, 0x1B, 0x2E, 0xBE, 0xBB, 0x30, 0x31]
MODS = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C]
LOCKS = [0x14, 0x90]
POOL = LETTERS + OTHERS + MODS + LOCKS


class Storm:
    def __init__(self, seed):
        self.rnd = random.Random(seed)
        self.physical = set()         # keys the cat/person is holding
        self.system = set()           # keys Windows thinks are down
        self.locks = {0x14: False, 0x90: True}
        self.last_pressed = None      # Windows only auto-repeats the last key pressed
        self.t = 1000.0
        self.f = cf.CatFilter(really_down=lambda vk: vk in self.system,
                              lock_on=lambda vk: self.locks.get(vk, False))
        self.events = 0

    def mods(self):
        m = 0
        for vk in self.system:
            m |= cf.MOD_BITS.get(vk, 0)
        return m

    def send(self, vk, down):
        """One real key event through the hook, applied to Windows' view."""
        self.events += 1
        blocked = self.f.on_key(vk, down, self.t, self.mods() if down else 0)
        if not blocked:
            if down:
                self.system.add(vk)
                if vk in self.locks and vk not in self.physical_repeat:
                    self.locks[vk] = not self.locks[vk]
            else:
                self.system.discard(vk)
        elif not down and self.f.replay_up is not None:
            replay, self.f.replay_up = self.f.replay_up, None
            assert replay == vk, f"replayed {replay:#x} for {vk:#x}"
            self.system.discard(vk)                     # dummy key, then the key-up
        if not down:
            assert vk not in self.system, f"stuck key {cf.key_name(vk)} after it was let go"
        assert len(self.f.held) <= len(POOL) and len(self.f.mod_t) <= len(POOL)
        assert len(self.f.swallowed) <= len(POOL) and len(self.f.incidents) <= 40

    def bypass(self, vk, down):
        """An event Windows sees but the hook doesn't (hook timed out)."""
        (self.system.add if down else self.system.discard)(vk)

    def step(self):
        r = self.rnd.random()
        self.t += self.rnd.choice((0.0, 0.002, 0.01, 0.02, 0.033, 0.06, 0.12, 0.3, 0.8, 2.5))
        self.physical_repeat = set()
        if r < 0.40:
            vk = self.rnd.choice(POOL)
            if vk not in self.physical:
                self.physical.add(vk)
                self.last_pressed = vk
                self.send(vk, True)
        elif r < 0.75 and self.physical:
            vk = self.rnd.choice(sorted(self.physical))
            self.physical.discard(vk)
            if vk == self.last_pressed:
                self.last_pressed = None
            if self.rnd.random() < 0.01:
                self.bypass(vk, False)
            else:
                self.send(vk, False)
        elif r < 0.93 and self.last_pressed is not None:
            self.physical_repeat = {self.last_pressed}
            for _ in range(self.rnd.randint(1, 20)):
                self.send(self.last_pressed, True)    # auto-repeat
                self.t += 0.033
        elif r < 0.95:
            self.f.set_enabled(self.rnd.random() < 0.8)
        elif r < 0.99:
            oid = self.rnd.choice(list(self.f.options))
            self.f.options[oid] = self.rnd.random() < 0.5
        else:
            self.locks[0x14] = self.rnd.random() < 0.5

    def finish(self):
        for vk in sorted(self.physical):
            self.t += 0.05
            self.send(vk, False)
        self.physical.clear()
        self.t += 5.0
        assert not self.system, f"keys left down: {[cf.key_name(v) for v in self.system]}"
        assert not self.f.cat_mode(self.t)
        self.f.set_enabled(True)
        self.f.options.update(cf.DEFAULT_OPTIONS)
        for i in range(3):                             # an ordinary word types again
            for ch in "kat":
                self.t += 0.15
                assert not self.f.on_key(ord(ch.upper()), True, self.t, 0), "keyboard jammed"
                self.system.add(ord(ch.upper()))
                self.t += 0.05
                self.send(ord(ch.upper()), False)


def main(storms=100, events=20000):
    start = time.perf_counter()
    total = 0
    for seed in range(storms):
        st = Storm(seed)
        try:
            while st.events < events:
                st.step()
            st.finish()
        except AssertionError as e:
            print(f"FAIL storm {seed} after {st.events} events: {e}")
            return 1
        total += st.events
    secs = time.perf_counter() - start
    print(f"OK  {storms} storms, {total:,} key events, no stuck keys, no jams ({secs:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*(int(a) for a in sys.argv[1:3])))
