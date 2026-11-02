"""Tests for the Cat Lock rules. Run: python test_catfilter.py"""
import unittest

import catfilter as cf

BS, SHIFT, CTRL, LALT, LWIN = 0x08, 0xA0, 0xA2, 0xA4, 0x5B
CAPS, NUMLOCK, INS, UP = 0x14, 0x90, 0x2D, 0x26


def code(ch):
    return ord(ch.upper()) if isinstance(ch, str) else ch


class Keys:
    """Plays key events into a CatFilter and records what got through."""

    def __init__(self, options=None, lock_on=None):
        self.f = cf.CatFilter(lambda vk: vk in self.sys_down, lock_on or (lambda vk: False))
        self.f.options.update(options or {})
        self.sys_down, self.typed = set(), []   # keys Windows saw go down

    def mods(self):
        m = 0
        for vk in self.sys_down:
            m |= cf.MOD_BITS.get(vk, 0)
        return m

    def press(self, ch, t):
        vk = code(ch)
        if not self.f.on_key(vk, True, t, self.mods()):
            self.sys_down.add(vk)
            if vk not in cf.MODIFIERS:
                self.typed.append(cf.key_name(vk))

    def release(self, ch, t):
        vk = code(ch)
        self.sys_down.discard(vk)
        return self.f.on_key(vk, False, t)

    def tap(self, ch, t, hold=0.08):
        self.press(ch, t)
        self.release(ch, t + hold)

    def hold(self, ch, t, secs):
        """Key held long enough to auto-repeat (500 ms delay, then every 33 ms)."""
        self.press(ch, t)
        r = t + 0.5
        while r < t + secs:
            vk = code(ch)
            if not self.f.on_key(vk, True, r, self.mods()):
                self.typed.append(cf.key_name(vk))
            r += 0.033

    def text(self):
        return "".join(self.typed)


class Typing(unittest.TestCase):
    def test_normal_typing_with_rollover(self):
        k = Keys()
        # next key goes down 70 ms after the last, each held 110 ms (overlapping)
        events = []
        words = "hello there my cat"
        for i, ch in enumerate(words):
            same_next = i + 1 < len(words) and words[i + 1] == ch   # one key can't overlap itself
            events += [(i * 0.07, "press", ch), (i * 0.07 + (0.05 if same_next else 0.11), "release", ch)]
        for t, what, ch in sorted(events, key=lambda e: (e[0], e[1] == "press")):
            getattr(k, what)(ch, t)
        self.assertEqual(k.text(), "hello there my cat".replace(" ", "Space"))

    def test_fast_overlapping_typing(self):
        k = Keys()
        for i, ch in enumerate("thequickbrown"):
            k.press(ch, i * 0.045)
            if i:
                k.release("thequickbrown"[i - 1], i * 0.045 + 0.02)
        self.assertEqual(k.text(), "thequickbrown")

    def test_capitals_with_shift(self):
        k = Keys()
        k.press(SHIFT, 0.0)
        k.tap("p", 0.015)          # shift and letter almost together is normal typing
        k.release(SHIFT, 0.1)
        k.tap("o", 0.2)
        self.assertEqual(k.text(), "po")

    def test_double_letter_ok_third_blocked(self):
        k = Keys()
        for i, ch in enumerate("passsed"):
            k.tap(ch, i * 0.2)
        self.assertEqual(k.text(), "passed")

    def test_www_and_roman_numerals(self):
        k = Keys()
        for i, ch in enumerate("wwwiii"):
            k.tap(ch, i * 0.2)
        self.assertEqual(k.text(), "wwwiii")

    def test_digits_not_limited(self):
        k = Keys()
        for i, ch in enumerate("1000"):
            k.tap(ch, i * 0.2)
        self.assertEqual(k.text(), "1000")

    def test_same_letter_slowly_is_fine(self):
        k = Keys()
        for i in range(3):
            k.tap("s", i * 3.0)
        self.assertEqual(k.text(), "sss")

    def test_shift_held_then_keys(self):
        k = Keys()
        k.press(SHIFT, 0.0)
        k.tap("a", 0.1)
        k.press("b", 0.7)          # shift held 0.7 s, still fine
        self.assertEqual(k.text(), "ab")


class Cat(unittest.TestCase):
    def test_held_letter_types_once(self):
        k = Keys()
        k.hold("c", 0.0, 3.0)
        self.assertEqual(k.text(), "c")
        self.assertFalse(k.release("c", 3.0))     # its key-up still goes through

    def test_held_backspace_repeats(self):
        k = Keys()
        k.hold(BS, 0.0, 1.0)
        self.assertGreater(k.typed.count("Backspace"), 10)

    def test_held_ctrl_z_repeats(self):
        k = Keys()
        k.press(CTRL, 0.0)
        k.hold("z", 0.2, 1.2)
        self.assertGreater(len(k.typed), 10)

    def test_ctrl_z_four_times(self):
        k = Keys()
        k.press(CTRL, 0.0)
        for i in range(4):
            k.tap("z", 0.2 + i * 0.2)
        self.assertEqual(k.text(), "zzzz")

    def test_two_keys_together_second_dropped(self):
        k = Keys()
        k.press("d", 0.0)
        k.press("f", 0.010)
        k.release("d", 0.15)
        self.assertTrue(k.release("f", 0.15))     # blocked key's key-up blocked too
        k.tap("o", 0.4)
        self.assertEqual(k.text(), "do")
        self.assertEqual(k.f.cat_visits, 0)

    def test_paw_of_three_starts_cat_mode(self):
        k = Keys()
        k.press("d", 0.0)
        k.press("f", 0.008)
        k.press("s", 0.015)
        for ch in "dfs":
            k.release(ch, 0.2)
        k.tap("j", 0.6)                           # still in cat mode
        k.tap("k", 1.8)                           # quiet for over a second
        self.assertEqual(k.text(), "dk")
        self.assertEqual(k.f.cat_visits, 1)

    def test_cat_standing_on_two_keys(self):
        k = Keys()
        k.press("i", 0.0)
        k.press("o", 0.2)          # rollover gap, so it goes through
        r = 0.7
        while r < 4.0:             # both held, o auto-repeats
            if not k.f.on_key(ord("O"), True, r):
                k.typed.append("o")
            r += 0.033
        self.assertEqual(k.text(), "io")
        self.assertTrue(k.f.cat_mode(3.9))

    def test_leaning_cat(self):
        k = Keys()
        k.press("j", 0.0)
        k.press("k", 0.8)          # j still held after 0.8 s
        k.press("l", 1.2)
        self.assertEqual(k.text(), "j")
        self.assertEqual(k.f.cat_visits, 1)

    def test_missed_key_up_cannot_jam_keyboard(self):
        k = Keys()
        k.press("q", 0.0)
        k.sys_down.discard(ord("Q"))   # Windows saw it go up but the key-up never reached us
        k.tap("w", 5.0)
        self.assertEqual(k.text(), "qw")

    def test_turned_off_lets_everything_through(self):
        k = Keys()
        k.f.set_enabled(False)
        k.hold("c", 0.0, 1.0)
        k.press(LWIN, 2.0)
        k.press("x", 2.2)
        self.assertGreater(len(k.typed), 10)
        self.assertEqual(k.typed[-1], "x")

    def test_turned_off_while_cat_holds_a_key(self):
        # found by test_stress.py: blocked key, then turned off, then its
        # repeat went through but its key-up was still held back = stuck key
        k = Keys()
        k.press("j", 0.0)
        k.press("k", 0.8)                         # leaning cat: k blocked
        k.f.set_enabled(False)
        k.f.on_key(ord("K"), True, 1.3, 0)        # auto-repeat goes through now
        k.sys_down.add(ord("K"))
        k.release("j", 1.5)
        self.assertFalse(k.release("K", 1.6))     # so its key-up must too

    def test_turned_on_while_a_key_is_held(self):
        # found by test_stress.py: key went down while off, Cat Lock turned on,
        # its auto-repeat looked like a new press and its key-up got blocked
        k = Keys()
        k.f.set_enabled(False)
        k.press(0x20, 0.0)
        k.f.set_enabled(True)
        for i in range(10):
            k.f.on_key(0x20, True, 0.6 + i * 0.033, 0)
        self.assertFalse(k.release(0x20, 1.2))
        k.f.set_enabled(False)
        k.press(LWIN, 2.0)
        k.f.options["win_all"] = True
        k.f.set_enabled(True)
        k.f.on_key(LWIN, True, 2.6, 0)            # Win's repeat must not be swallowed now
        self.assertFalse(k.release(LWIN, 3.0))

    def test_incidents_grouped(self):
        k = Keys()
        k.hold("c", 0.0, 2.0)
        self.assertEqual(len(k.f.incidents), 1)
        inc = k.f.incidents[0]
        self.assertEqual((inc["kind"], inc["keys"]), ("held", ["c"]))
        self.assertGreater(inc["count"], 30)


class BadShortcuts(unittest.TestCase):
    def test_win_x_blocked_and_start_menu_kept_shut(self):
        k = Keys()
        k.press(LWIN, 0.0)
        k.tap("x", 0.2)
        self.assertEqual(k.text(), "")
        self.assertTrue(k.release(LWIN, 0.4))     # replayed after a dummy key instead
        self.assertEqual(k.f.replay_up, LWIN)
        self.assertEqual(k.f.incidents[-1]["keys"], ["Win+X"])

    def test_win_e_allowed(self):
        k = Keys()
        k.press(LWIN, 0.0)
        k.tap("e", 0.2)
        self.assertFalse(k.release(LWIN, 0.4))
        self.assertEqual(k.text(), "e")
        self.assertIsNone(k.f.replay_up)

    def test_win_alone_only_when_ticked(self):
        k = Keys()
        k.press(LWIN, 0.0)
        self.assertFalse(k.release(LWIN, 0.1))
        k = Keys({"win_alone": True})
        k.press(LWIN, 0.0)
        self.assertTrue(k.release(LWIN, 0.1))
        self.assertEqual(k.f.replay_up, LWIN)

    def test_every_win_shortcut(self):
        k = Keys({"win_all": True})
        k.press(LWIN, 0.0)
        k.tap("e", 0.2)                           # Windows never saw Win, so just "e"
        self.assertTrue(k.release(LWIN, 0.4))
        self.assertEqual(k.text(), "e")
        self.assertIsNone(k.f.replay_up)

    def test_ctrl_w_only_when_ticked(self):
        k = Keys()
        k.press(CTRL, 0.0)
        k.tap("w", 0.2)
        self.assertEqual(k.text(), "w")
        k = Keys({"close_tab": True})
        k.press(CTRL, 0.0)
        k.tap("w", 0.2)
        self.assertEqual(k.text(), "")

    def test_shortcut_by_paw(self):
        k = Keys()
        k.press(CTRL, 0.0)
        k.tap("w", 0.010)                         # landed with Ctrl: blocked
        k.release(CTRL, 0.2)
        k.press(CTRL, 1.0)
        k.tap("w", 1.15)                          # a person: Ctrl first, then W
        self.assertEqual(k.text(), "w")
        self.assertEqual(k.f.incidents[0]["kind"], "pawcut")

    def test_alt_held_when_blocked_is_replayed(self):
        k = Keys()
        k.press(CTRL, 0.0)
        k.press(LALT, 0.1)
        k.tap(UP, 0.3)                            # Ctrl+Alt+Up turns the screen
        self.assertEqual(k.text(), "")
        self.assertTrue(k.release(LALT, 0.5))
        self.assertEqual(k.f.replay_up, LALT)
        self.assertFalse(k.release(CTRL, 0.5))

    def test_insert_alone_blocked_shift_insert_pastes(self):
        k = Keys()
        k.tap(INS, 0.0)
        k.press(SHIFT, 1.0)
        k.tap(INS, 1.2)
        self.assertEqual(k.text(), "Insert")

    def test_num_lock_kept(self):
        k = Keys()
        self.assertTrue(k.f.on_key(NUMLOCK, True, 0.0, 0))
        self.assertTrue(k.f.on_key(NUMLOCK, True, 0.5, 0))   # its repeats too
        self.assertTrue(k.f.on_key(NUMLOCK, False, 0.6, 0))

    def test_caps_lock_can_only_go_off(self):
        on = [False]
        k = Keys({"capslock": True}, lock_on=lambda vk: on[0])
        self.assertTrue(k.f.on_key(CAPS, True, 0.0, 0))
        self.assertTrue(k.f.on_key(CAPS, False, 0.1, 0))
        on[0] = True
        self.assertFalse(k.f.on_key(CAPS, True, 1.0, 0))
        self.assertFalse(k.f.on_key(CAPS, False, 1.1, 0))

    def test_typing_rules_can_be_switched_off(self):
        k = Keys({"rule_held": False, "rule_paw": False, "rule_triple": False})
        k.hold("c", 0.0, 1.0)
        k.release("c", 1.0)
        held = len(k.typed)
        k.press("d", 2.0)
        k.press("f", 2.01)
        for ch in "dfsss":
            k.release(ch, 2.1)
        for i in range(3):
            k.tap("s", 3.0 + i * 0.2)
        self.assertGreater(held, 10)
        self.assertTrue(k.text().endswith("dfsss"))

    def test_every_option_parses_and_has_a_group(self):
        for oid, group, label, on, combos in cf.BAD_KEYS:
            self.assertIn(group, cf.BAD_GROUPS)
        self.assertIn(0xBE, cf.RULES)                 # Win+. is the period key, not Delete
        self.assertNotIn(("win_emoji", cf.WIN, False), cf.RULES.get(0x2E, []))


if __name__ == "__main__":
    unittest.main(verbosity=1)
