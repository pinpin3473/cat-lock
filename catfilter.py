"""Cat Lock rules: decides, key by key, whether a keystroke came from the cat.

Nothing in here talks to Windows, so the rules can be tested on their own
(test_catfilter.py). Times are in seconds.

The rules
  1. A held key types once. Holding c gives "c", not "cccccc"
     (Backspace, Delete, arrows, Home/End, Page Up/Down and volume still repeat).
  2. Two keys landing together (within PAW_S) - the second one is dropped.
     Normal fast typing, where the next key goes down before the last one is
     up, is allowed: those keys are further apart than a paw.
  3. Three keys landing together, a key pressed while another has been held
     for LEAN_S, or two keys held down together = cat on the keyboard.
     Everything is blocked until the keyboard has been quiet for QUIET_S.
  4. The same letter three times in a row - the third is dropped
     (not W, for www, and not I, for Roman numerals like Joao III).
  Rules 1, 2 and 4 can each be switched off ("Typing rules" in the window).
  5. Bad shortcuts (BAD_KEYS, each switched on or off in the window), and any
     shortcut whose key goes down at the same instant as Ctrl, Alt or Win.
     When a shortcut is blocked while Win or Alt is held, letting go of Win/Alt
     is replayed with a dummy key first, so the Start menu / menu bar stays shut.
Shift, Ctrl, Alt and Win themselves are never blocked (unless ticked), and
Ctrl/Alt/Win shortcuts (Ctrl+Z three times, held Ctrl+Z) skip rules 1 and 4.
"""
import time
from collections import deque

# ---- settings -------------------------------------------------------------
PAW_S = 0.030       # keys going down this close together = one paw
LEAN_S = 0.5        # a key already held this long when another goes down = cat leaning
QUIET_S = 1.0       # cat mode ends after this long with no cat-like key activity
SAME_GAP_S = 2.0    # 3 presses of one letter, each within this of the last, = blocked
STALE_S = 1.5       # a blocked key not heard from for this long counts as let go
TRIPLE_OK = {ord("W"), ord("I")}

CTRL, ALT, SHIFT, WIN = 1, 2, 4, 8
MOD_BITS = {0x10: SHIFT, 0xA0: SHIFT, 0xA1: SHIFT, 0x11: CTRL, 0xA2: CTRL, 0xA3: CTRL,
            0x12: ALT, 0xA4: ALT, 0xA5: ALT, 0x5B: WIN, 0x5C: WIN}
WIN_VKS = {0x5B, 0x5C}
ALT_VKS = {0x12, 0xA4, 0xA5}
# Shift, Ctrl, Alt, Win, Caps Lock, Num Lock, Scroll Lock
MODIFIERS = set(MOD_BITS) | {0x14, 0x90, 0x91}
# Keys allowed to keep repeating while held
REPEAT_OK = {0x08, 0x2E, 0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22,
             0xAE, 0xAF}

NAMES = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x20: "Space",
         0x2E: "Delete", 0x2D: "Insert", 0x25: "Left", 0x26: "Up", 0x27: "Right",
         0x28: "Down", 0x24: "Home", 0x23: "End", 0x21: "PgUp", 0x22: "PgDn",
         0x2C: "PrtScn", 0x14: "CapsLock", 0x90: "NumLock", 0x5B: "Win", 0x5C: "Win",
         0x5F: "Sleep", 0x6B: "+", 0x6D: "-",
         0xBA: ";", 0xBB: "+", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
         0xC0: "'", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "#", 0xDF: "`"}

KINDS = {"cat": "Cat on keyboard", "paw": "Two keys at once",
         "held": "Key held down", "triple": "Same letter 3 times",
         "bad": "Bad shortcut", "pawcut": "Shortcut by paw"}

# ---- bad shortcuts ----------------------------------------------------------
# (id, group, label, blocked by default, key combos)
# "Win+X" = X pressed while Win is held (extra modifiers held too still count).
# A plain key ("Insert") only counts with no Ctrl/Alt/Win/Shift held, so
# Shift+Insert still pastes. "*Key" counts whatever is held.
BAD_GROUPS = ["Windows key", "Typing rules", "Ctrl and Alt", "Single keys"]
BAD_KEYS = [
    ("win_x", "Windows key", "Win+X — power menu (shut down, restart)", True, ["Win+X"]),
    ("win_p", "Windows key", "Win+P — projector (can switch the screen off)", True, ["Win+P"]),
    ("win_z", "Windows key", "Win+Z — snap layouts", True, ["Win+Z"]),
    ("win_narrator", "Windows key", "Win+Ctrl+Enter — Narrator (talks)", True, ["Win+Ctrl+Enter"]),
    ("win_desktops", "Windows key", "Win+Ctrl+D / F4 / arrows — virtual desktops", True,
     ["Win+Ctrl+D", "Win+Ctrl+F4", "Win+Ctrl+Left", "Win+Ctrl+Right"]),
    ("win_colour", "Windows key", "Win+Ctrl+C — colour filter (grey screen)", True, ["Win+Ctrl+C"]),
    ("win_graphics", "Windows key", "Win+Ctrl+Shift+B — graphics restart", True, ["Win+Ctrl+Shift+B"]),
    ("win_magnifier", "Windows key", "Win+Plus / Minus — Magnifier", True, ["Win+Plus", "Win+Minus"]),
    ("win_space", "Windows key", "Win+Space — switches keyboard language", True, ["Win+Space"]),
    ("win_voice", "Windows key", "Win+H / G / Alt+R — dictation, Game Bar, recording", True,
     ["Win+H", "Win+G", "Win+Alt+R", "Win+Alt+K"]),
    ("win_emoji", "Windows key", "Win+. — emoji panel", True, ["Win+Period"]),
    ("win_tab", "Windows key", "Win+Tab — task view", False, ["Win+Tab"]),
    ("win_d", "Windows key", "Win+D / Win+M — hide all windows", False, ["Win+D", "Win+M"]),
    ("win_arrows", "Windows key", "Win+arrows — snap or minimise windows", False,
     ["Win+Up", "Win+Down", "Win+Left", "Win+Right"]),
    ("win_alone", "Windows key", "Win on its own — opens Start", False, []),
    ("win_all", "Windows key", "Every Windows key shortcut", False, ["*Win"]),
    ("rule_held", "Typing rules", "Held key types once (no cccccc)", True, []),
    ("rule_paw", "Typing rules", "Two keys landing together", True, []),
    ("rule_triple", "Typing rules", "Same letter 3 times (www, iii allowed)", True, []),
    ("paw_shortcut", "Ctrl and Alt", "Shortcut pressed at the same instant (paw)", True, []),
    ("screen_rotate", "Ctrl and Alt", "Ctrl+Alt+arrows — turns the screen round", True,
     ["Ctrl+Alt+Up", "Ctrl+Alt+Down", "Ctrl+Alt+Left", "Ctrl+Alt+Right"]),
    ("task_manager", "Ctrl and Alt", "Ctrl+Shift+Esc — Task Manager", True, ["Ctrl+Shift+Esc"]),
    ("clear_history", "Ctrl and Alt", "Ctrl+Shift+Delete — clear browsing data", True, ["Ctrl+Shift+Delete"]),
    ("alt_f4", "Ctrl and Alt", "Alt+F4 — close window / shut down", False, ["Alt+F4"]),
    ("close_tab", "Ctrl and Alt", "Ctrl+W / F4 / Q — close tab or program", False,
     ["Ctrl+W", "Ctrl+F4", "Ctrl+Q"]),
    ("ctrl_enter", "Ctrl and Alt", "Ctrl+Enter — send email or message", False, ["Ctrl+Enter"]),
    ("ctrl_p", "Ctrl and Alt", "Ctrl+P — print", False, ["Ctrl+P"]),
    ("insert", "Single keys", "Insert — typing over text", True, ["Insert"]),
    ("numlock", "Single keys", "Num Lock — stays as it is", True, ["*NumLock"]),
    ("capslock", "Single keys", "Caps Lock — can still switch it off", False, ["*CapsLock"]),
    ("f1", "Single keys", "F1 — help page", True, ["F1"]),
    ("launch_keys", "Single keys", "Sleep, browser, mail and app keys", True,
     ["*Sleep", "*BrowserKeys", "*AppKeys"]),
    ("prtscn", "Single keys", "Print Screen — Snipping Tool", False, ["PrtScn"]),
]
DEFAULT_OPTIONS = {oid: on for oid, _g, _l, on, _c in BAD_KEYS}

KEY_CODES = {"Enter": [0x0D], "Space": [0x20], "Tab": [0x09], "Esc": [0x1B], "Delete": [0x2E],
             "Insert": [0x2D], "Up": [0x26], "Down": [0x28], "Left": [0x25], "Right": [0x27],
             "Plus": [0xBB, 0x6B], "Minus": [0xBD, 0x6D], "Period": [0xBE], "PrtScn": [0x2C],
             "CapsLock": [0x14], "NumLock": [0x90], "Win": [0x5B, 0x5C], "Sleep": [0x5F],
             "BrowserKeys": list(range(0xA6, 0xAD)), "AppKeys": list(range(0xB4, 0xB8))}
MOD_WORDS = {"Ctrl": CTRL, "Alt": ALT, "Shift": SHIFT, "Win": WIN}


def _parse(combo):
    anymods = combo.startswith("*")
    parts = combo.lstrip("*").split("+")
    need = 0
    for word in parts[:-1]:
        need |= MOD_WORDS[word]
    key = parts[-1]
    if key in KEY_CODES:
        vks = KEY_CODES[key]
    elif len(key) == 1:
        vks = [ord(key.upper())]
    else:
        vks = [0x6F + int(key[1:])]          # F1..F24
    return [(vk, need, anymods) for vk in vks]


RULES = {}   # vk -> [(option id, modifiers needed, any modifiers ok)]
for _oid, _g, _l, _on, _combos in BAD_KEYS:
    for _c in _combos:
        for _vk, _need, _any in _parse(_c):
            RULES.setdefault(_vk, []).append((_oid, _need, _any))


def key_name(vk):
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x60 <= vk <= 0x69:
        return f"num{vk - 0x60}"
    return NAMES.get(vk, f"#{vk}")


def combo_name(mods, vk):
    words = [w for w, bit in (("Win", WIN), ("Ctrl", CTRL), ("Alt", ALT), ("Shift", SHIFT)) if mods & bit]
    name = key_name(vk)
    return "+".join(words + [name.upper() if len(name) == 1 else name])


class Held:
    __slots__ = ("t_down", "t_last", "passed")

    def __init__(self, t, passed):
        self.t_down = self.t_last = t
        self.passed = passed


class CatFilter:
    def __init__(self, really_down=lambda vk: True, lock_on=lambda vk: False):
        # really_down(vk) says whether Windows still sees a key we let through as
        # held, so a missed key-up can never leave a "stuck" key that blocks typing.
        # lock_on(vk) says whether Caps Lock / Num Lock is switched on.
        self.really_down = really_down
        self.lock_on = lock_on
        self.enabled = True
        self.options = dict(DEFAULT_OPTIONS)
        self.held = {}              # vk -> Held, non-modifier keys physically down right now
        self.mod_t = {}             # modifier vk -> when it went down (ones we let through)
        self.swallowed = {}         # modifier vk -> last heard, ones we threw away
        self.need_mask = set()      # Win/Alt keys held while we blocked something
        self.win_used = True        # another key went down while Win was held
        self.replay_up = None       # set when a key-up must be re-sent after a dummy key
        self.cat_until = 0.0
        self.last_vk, self.last_t, self.run = None, 0.0, 0
        self.blocked = 0
        self.cat_visits = 0
        self.incidents = deque(maxlen=40)   # newest last; read by the window
        self.changes = 0                    # bumps whenever incidents change
        self._group = None

    def set_enabled(self, on):
        self.enabled = on
        self.cat_until = 0.0
        self.last_vk = None

    def cat_mode(self, t):
        return t < self.cat_until

    # ---- one key event ----------------------------------------------------
    def on_key(self, vk, down, t, mods=0):
        """Return True to throw the key event away. mods = CTRL|ALT|SHIFT|WIN bits
        Windows sees held at that moment."""
        if not down:
            return self._release(vk)
        if vk not in WIN_VKS:
            self.win_used = True
        self._forget_released(t, vk)
        if (vk not in self.held and vk not in self.mod_t and vk not in self.swallowed
                and self.really_down(vk)):
            # Windows already has this key down (it went through while Cat Lock was
            # off), so this is its auto-repeat: adopt it, and never hold back its key-up
            if vk in MODIFIERS:
                self.mod_t[vk] = t
            else:
                self.held[vk] = Held(t, True)
        if vk in MODIFIERS:
            return self._modifier(vk, t, mods)
        if not self.enabled:
            k = self.held.get(vk)
            if k is not None:
                k.passed = True     # Windows now sees it down, so its key-up must go through too
            return False
        k = self.held.get(vk)
        if k is not None:
            return self._repeat(vk, k, t, mods & (CTRL | ALT | WIN))
        return self._press(vk, t, mods)

    def _release(self, vk):
        passed_down = self.mod_t.pop(vk, None) is not None
        if self.swallowed.pop(vk, None) is not None:
            return True
        alone = (vk in WIN_VKS and passed_down and not self.win_used
                 and self.enabled and self.options.get("win_alone"))
        if vk in self.need_mask or alone:
            self.need_mask.discard(vk)
            if alone:
                self._add(("alone", time.time()), "bad", name="Win on its own")
            self.replay_up = vk
            return True
        k = self.held.pop(vk, None)
        return k is not None and not k.passed   # the app never saw its key-down

    def _forget_released(self, t, current):
        for vk, k in list(self.held.items()):
            if vk != current and ((not self.really_down(vk)) if k.passed else (t - k.t_last > STALE_S)):
                del self.held[vk]
        for vk in list(self.mod_t):
            if vk != current and not self.really_down(vk):
                del self.mod_t[vk]
        for vk, last in list(self.swallowed.items()):
            if vk != current and t - last > STALE_S:
                del self.swallowed[vk]

    def _modifier(self, vk, t, mods):
        if vk in self.swallowed:
            self.swallowed[vk] = t
            return True                      # auto-repeat of a key we threw away
        if vk in self.mod_t:
            return False                     # auto-repeat
        if vk in WIN_VKS:
            self.win_used = False
        if self.enabled:
            bad = self._bad(vk, mods, t)
            if bad:
                self.swallowed[vk] = t
                self._add(("bad", vk, t), bad[0], name=bad[1])
                return True
        self.mod_t[vk] = t
        return False

    def _bad(self, vk, mods, t):
        """(kind, name) if this key is a ticked bad shortcut, else None."""
        for oid, need, anymods in RULES.get(vk, ()):
            if not self.options.get(oid):
                continue
            if anymods or (need and mods & need == need) or (not need and not mods):
                if oid == "capslock" and self.lock_on(vk):
                    continue                 # Caps Lock is on: let it be switched off
                return "bad", (key_name(vk) if anymods else combo_name(mods, vk))
        if (self.options.get("paw_shortcut") and mods & (CTRL | ALT | WIN)
                and vk not in MODIFIERS
                and any(t - mt <= PAW_S for mvk, mt in self.mod_t.items()
                        if MOD_BITS.get(mvk, 0) & (CTRL | ALT | WIN))):
            return "pawcut", combo_name(mods, vk)
        return None

    def _repeat(self, vk, k, t, combo):
        """Windows auto-repeat: the key is still down."""
        k.t_last = t
        if not k.passed and not self.cat_mode(t) and not any(v != vk for v in self.held):
            return True                      # repeat of a key blocked for another reason
        if self.cat_mode(t) or any(v != vk for v in self.held):
            return self._cat(vk, t)          # held together with another key
        if vk in REPEAT_OK or combo or not self.options.get("rule_held"):
            return False
        self._add(("held", vk, k.t_down), "held", vk)
        return True

    def _press(self, vk, t, mods):
        bad = self._bad(vk, mods, t)
        if bad:
            self.held[vk] = Held(t, False)
            self.last_vk = None
            self._add(("bad", vk, t), bad[0], name=bad[1])
            return True
        others = [o for v, o in self.held.items() if v != vk]
        paw = sum(1 for o in others if t - o.t_down <= PAW_S)
        lean = any(t - o.t_down >= LEAN_S for o in others)
        if self.cat_mode(t) or lean or paw >= 2:
            self.held[vk] = Held(t, False)
            return self._cat(vk, t, extend=lean or paw > 0)
        if paw and self.options.get("rule_paw"):
            self.held[vk] = Held(t, False)
            self.last_vk = None
            self._add(("paw", t), "paw", vk)
            return True
        if vk == self.last_vk and t - self.last_t <= SAME_GAP_S:
            self.run += 1
        else:
            self.run = 1
        self.last_vk, self.last_t = vk, t
        combo = mods & (CTRL | ALT | WIN)
        if (self.run >= 3 and 0x41 <= vk <= 0x5A and vk not in TRIPLE_OK and not combo
                and self.options.get("rule_triple")):
            self.held[vk] = Held(t, False)
            self._add(("triple", vk), "triple", vk)
            return True
        self.held[vk] = Held(t, True)
        return False

    def _cat(self, vk, t, extend=True):
        if not self.cat_mode(t):
            self.cat_visits += 1
            self.cat_until = t + QUIET_S
        elif extend:
            self.cat_until = t + QUIET_S
        self.last_vk = None
        self._add(("cat", self.cat_visits), "cat", vk)
        return True

    def _add(self, group, kind, vk=None, name=None):
        self.blocked += 1
        self.changes += 1
        # Win or Alt let go with nothing in between would open Start / the menu bar
        self.need_mask.update(v for v in self.mod_t if v in WIN_VKS or v in ALT_VKS)
        name = name or key_name(vk)
        if group == self._group and self.incidents:
            inc = self.incidents[-1]
            inc["count"] += 1
            if len(inc["keys"]) < 10 and name not in inc["keys"]:
                inc["keys"].append(name)
            return
        self._group = group
        self.incidents.append({"when": time.strftime("%H:%M"), "kind": kind,
                               "count": 1, "keys": [name]})
