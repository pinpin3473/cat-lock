"""Cat Lock - stops the cat typing.

Watches the keyboard with a Windows low-level keyboard hook and throws away
keystrokes that look like a cat (rules in catfilter.py). It only looks at key
events, uses no CPU in between, and saves nothing you type.

Run with pythonw (Desktop shortcut "Cat Lock"). --min starts it hidden in the tray.
The X button hides the window; Quit is on the tray icon's right-click menu.
"""
import ctypes
import json
import os
import queue
import sys
import threading
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

if sys.platform != "win32":
    sys.exit("Cat Lock only runs on Windows.")

import catfilter
import shortcuts

HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "cat_lock_settings.json"

# ---- Windows bits -----------------------------------------------------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_QUIT, WM_APP_REHOOK = 0x0012, 0x8001
LLKHF_INJECTED = 0x10                  # typed by software (on-screen keyboard etc.): left alone
MOD_KEYS = ((0x11, catfilter.CTRL), (0x12, catfilter.ALT), (0x10, catfilter.SHIFT),
            (0x5B, catfilter.WIN), (0x5C, catfilter.WIN))
MASK_VK = 0xE8                         # unassigned key, tapped so Win/Alt alone does nothing
LRESULT = ctypes.c_ssize_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyState.restype = ctypes.c_short
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetTickCount64.restype = ctypes.c_ulonglong


def now():
    return kernel32.GetTickCount64() / 1000.0


def key_is_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def lock_is_on(vk):
    return bool(user32.GetKeyState(vk) & 1)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _Union(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("size", ctypes.c_byte * 32)]   # as big as MOUSEINPUT
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _Union)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def mask_then_release(vk):
    """Let go of Win/Alt after a blocked shortcut without Windows opening the
    Start menu or the menu bar: tap an unused key first, then send the key-up.
    Returns False if Windows refused (e.g. an admin window has the focus), so
    the real key-up can go through instead and the key is never left stuck."""
    extended = 1 if vk in (0x5B, 0x5C, 0xA5) else 0
    keys = (INPUT * 3)()
    for item, (code, flags) in zip(keys, ((MASK_VK, 0), (MASK_VK, 2), (vk, extended | 2))):
        item.type = 1                                   # INPUT_KEYBOARD
        item.ki.wVk, item.ki.dwFlags = code, flags
    return user32.SendInput(3, keys, ctypes.sizeof(INPUT)) == 3


class KeyboardHook(threading.Thread):
    """Owns the hook and its message loop. Windows quietly drops a hook that is
    ever too slow to answer, so the window asks for a fresh one every few minutes."""

    def __init__(self, filt):
        super().__init__(daemon=True)
        self.filt = filt
        self.hook = None
        self.tid = None
        self.proc = HOOKPROC(self._proc)

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 2)   # highest
        self._install()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_REHOOK:
                self._install()
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)

    def _install(self):
        new = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self.proc, kernel32.GetModuleHandleW(None), 0)
        if new:
            old, self.hook = self.hook, new
            if old:
                user32.UnhookWindowsHookEx(old)

    def _proc(self, code, wparam, lparam):
        try:
            if code == 0:
                kb = KBDLLHOOKSTRUCT.from_address(lparam)
                if not kb.flags & LLKHF_INJECTED:
                    tick = kernel32.GetTickCount64()
                    t = (tick - ((tick - kb.time) & 0xFFFFFFFF)) / 1000.0   # when the key moved
                    down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    mods = 0
                    if down:
                        for v, bit in MOD_KEYS:
                            if key_is_down(v):
                                mods |= bit
                    if self.filt.on_key(kb.vkCode, down, t, mods):
                        up, self.filt.replay_up = self.filt.replay_up, None
                        if up is None or mask_then_release(up):
                            return 1
                        # replay refused: let the real key-up through rather than leave it stuck
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def post(self, message):
        if self.tid:
            user32.PostThreadMessageW(self.tid, message, 0, 0)


# ---- tray icon ------------------------------------------------------------------
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
WM_TRAY, WM_CLOSE, WM_DESTROY = 0x8002, 0x0010, 0x0002
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 0x10
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int,
                              ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.LPVOID]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

TRAY_TIPS = {"watch": "Cat Lock - watching", "cat": "Cat Lock - cat on the keyboard!",
             "off": "Cat Lock - off", "fail": "Cat Lock - not working"}
TRAY_ICONS = {"watch": "tray_watch.ico", "cat": "tray_cat.ico", "off": "tray_off.ico", "fail": "tray_off.ico"}
MENU = {1: "show", 2: "toggle", 3: "options", 4: "quit"}
WM_SHOW_APP = 0x8003      # sent by a second copy of Cat Lock: "show yourself"


class TrayIcon(threading.Thread):
    """The sleeping cat by the clock. Runs its own little message loop; clicks
    are handed to the window through a queue (commands)."""

    def __init__(self, commands):
        super().__init__(daemon=True)
        self.commands = commands
        self.hwnd = None
        self.state, self.enabled = "watch", True
        self.ready = threading.Event()
        self.proc = WNDPROC(self._wndproc)
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        size = user32.GetSystemMetrics(49)    # small icon size for this screen's zoom
        self.icons = {state: user32.LoadImageW(None, str(HERE / name), 1, size, size, 0x10)
                      for state, name in TRAY_ICONS.items()}

    def run(self):
        try:
            ux = ctypes.WinDLL("uxtheme")
            ux[135](2)     # SetPreferredAppMode(ForceDark): dark right-click menu
            ux[136]()      # FlushMenuThemes
        except Exception:
            pass
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self.proc, hInstance=hinst, lpszClassName="CatLockTray")
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "CatLockTray", "Cat Lock tray", 0, 0, 0, 0, 0,
                                           None, None, hinst, None)
        if self.hwnd and not self._notify(NIM_ADD):
            self.hwnd = None
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnregisterClassW("CatLockTray", hinst)

    def _notify(self, action, info=None):
        nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1,
                              uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP, uCallbackMessage=WM_TRAY,
                              hIcon=self.icons[self.state], szTip=TRAY_TIPS[self.state])
        if info:
            nid.uFlags |= NIF_INFO
            nid.szInfoTitle, nid.szInfo = "Cat Lock", info
        return shell32.Shell_NotifyIconW(action, ctypes.byref(nid))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONUP:
                self.commands.put("show_hide")
            elif event == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_DESTROY:                      # Quit: end this thread's message loop
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_SHOW_APP:
            self.commands.put("show")
            return 0
        if msg == self.taskbar_created:            # Explorer restarted: put the cat back
            self._notify(NIM_ADD)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0, 1, "Show Cat Lock")
        user32.AppendMenuW(menu, 0, 2, "Turn off" if self.enabled else "Turn on")
        user32.AppendMenuW(menu, 0, 3, "Bad shortcuts")
        user32.AppendMenuW(menu, 0x800, 0, None)    # separator
        user32.AppendMenuW(menu, 0, 4, "Quit Cat Lock")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)      # so the menu closes when you click elsewhere
        cmd = user32.TrackPopupMenu(menu, 0x0100 | 0x0020 | 0x0002, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, 0, 0, 0)
        user32.DestroyMenu(menu)
        if cmd in MENU:
            self.commands.put(MENU[cmd])

    # called from the window's thread
    def show_state(self, state, enabled):
        self.enabled = enabled
        if state != self.state:
            self.state = state
            if self.hwnd:
                self._notify(NIM_MODIFY)

    def balloon(self, text):
        if self.hwnd:
            self._notify(NIM_MODIFY, info=text)

    def remove(self):
        if self.hwnd:
            self._notify(NIM_DELETE)
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.hwnd = None


# ---- look -------------------------------------------------------------------
BG = "#1e1f22"
PANEL = "#26282c"
FIELD = "#141517"
FG = "#e4e5e7"
MUTED = "#9da1a8"
ACCENT = "#3b7ddd"
ACCENT_HI = "#5390ea"
BTN = "#34373d"
BTN_HI = "#40444b"
GOLD = "#e8b931"
GREEN = "#63d283"
RED = "#ff6b6b"
UI_FONT = ("Segoe UI", 10)
UI_BOLD = ("Segoe UI", 10, "bold")
SCALE = [1.0]   # screen zoom (125%, 150%...), set when the window opens


def px(n):
    return int(round(n * SCALE[0]))

BLUE = "#2784e3"
TRAIL = "#2e3136"   # paw prints in the header, just lighter than PANEL
CAT_RED = "#5a1c1f"

STATES = {   # headline, small line, card colour, headline colour, small line colour, picture
    "watch": ("Watching for the cat", "All quiet on the keyboard", PANEL, FG, MUTED, "watch"),
    "cat": ("Cat on the keyboard!", "Paws detected \u2014 keys blocked", CAT_RED, "#ffd7d7", "#f2a7a7", "cat"),
    "off": ("Cat Lock is off", "Every key goes through", PANEL, MUTED, "#70747b", "off"),
    "fail": ("Not watching the keyboard", "Quit and open Cat Lock again", CAT_RED, "#ffd7d7", "#f2a7a7", "off"),
}


def round_rect(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


def paw(c, x, y, size, colour):
    """A paw print centred on x, y: one big pad and four toes."""
    c.create_oval(x - size * 0.3, y - size * 0.05, x + size * 0.3, y + size * 0.42, fill=colour, outline="")
    for dx, dy in ((-0.4, -0.22), (-0.15, -0.42), (0.15, -0.42), (0.4, -0.22)):
        r = size * 0.11
        c.create_oval(x + dx * size - r, y + dy * size - r * 1.2, x + dx * size + r, y + dy * size + r * 1.2,
                      fill=colour, outline="")


def load_art(name):
    """A picture from art\\, drawn for the zoom nearest this screen's."""
    zoom = min((100, 125, 150, 175, 200, 250, 300), key=lambda z: abs(z - SCALE[0] * 100))
    try:
        return tk.PhotoImage(file=str(HERE / "art" / f"{name}@{zoom}.png"))
    except tk.TclError:
        return ""          # picture missing: the window just goes without it


class RoundButton(tk.Canvas):
    def __init__(self, master, text, command, width=170, height=34, primary=False):
        width, height = px(width), px(height)
        super().__init__(master, width=width, height=height, bg=master["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.command, self.w, self.h = command, width, height
        self.text, self.primary, self.hover = text, primary, False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", lambda e: self.command())
        self._draw()

    def configure_button(self, text=None, primary=None):
        if text is not None:
            self.text = text
        if primary is not None:
            self.primary = primary
        self._draw()

    def _set_hover(self, on):
        self.hover = on
        self._draw()

    def _draw(self):
        self.delete("all")
        if self.primary:
            fill, fg = (ACCENT_HI if self.hover else ACCENT), "white"
        else:
            fill, fg = (BTN_HI if self.hover else BTN), FG
        w, h, r = self.w, self.h, px(10)
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0]
        self.create_polygon(pts, smooth=True, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg,
                         font=UI_BOLD if self.primary else UI_FONT)


# ---- window -----------------------------------------------------------------
class CatLockApp:
    def __init__(self, root, filt, hook, tray, commands):
        self.root, self.filt, self.hook = root, filt, hook
        self.tray, self.commands = tray, commands
        self.told_about_tray = False
        self.quitting = False
        self.shown_changes = -1
        self.state = None
        self.opt_win = None
        self.settings = self._load_settings()
        saved = self.settings.get("options", {})
        filt.options.update({k: bool(v) for k, v in saved.items() if k in filt.options})
        SCALE[0] = max(1.0, root.winfo_fpixels("1i") / 96)
        root.title("Cat Lock")
        root.configure(bg=BG)
        root.minsize(px(440), px(420))
        try:
            root.iconbitmap(str(HERE / "icon.ico"))
        except tk.TclError:
            pass

        self.art = {name: load_art(name) for name in
                    ("card_watch", "card_cat", "card_off", "head", "paw_gold", "paw_red")}

        # header: little sleeping cat, name, and a trail of paw prints walking off
        self.header = tk.Canvas(root, height=px(50), bg=PANEL, highlightthickness=0)
        self.header.pack(fill="x")
        self.header.bind("<Configure>", lambda e: self._draw_header())

        # status card: the cat itself, asleep / awake / grey
        self.card = tk.Canvas(root, height=px(100), bg=BG, highlightthickness=0)
        self.card.pack(fill="x", padx=px(12), pady=(px(12), px(8)))
        self.card.bind("<Configure>", lambda e: self._draw_card())

        # two tiles: keys blocked, cat visits
        tiles = tk.Frame(root, bg=BG)
        tiles.pack(fill="x", padx=px(12))
        tiles.columnconfigure((0, 1), weight=1, uniform="tile")
        self.tiles = []
        for col, (icon, label) in enumerate((("key", "keys blocked"), ("paw", "cat visits"))):
            c = tk.Canvas(tiles, height=px(58), bg=BG, highlightthickness=0)
            c.grid(row=0, column=col, sticky="ew", padx=(0, px(4)) if col == 0 else (px(4), 0))
            c.bind("<Configure>", lambda e: self._draw_tiles())
            self.tiles.append((c, icon, label))

        tk.Label(root, text="RECENTLY BLOCKED", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=px(14), pady=(px(10), px(2)))

        buttons = tk.Frame(root, bg=BG)
        buttons.pack(side="bottom", fill="x", padx=px(12), pady=(px(10), px(12)))
        self.onoff = RoundButton(buttons, "Turn off", self.toggle, width=100)
        self.onoff.pack(side="left")
        RoundButton(buttons, "Bad shortcuts", self.open_options, width=130).pack(side="left", padx=(8, 0))
        self.startup = RoundButton(buttons, "", self.toggle_startup, width=170)
        self.startup.pack(side="right")
        self._show_startup()

        self.log = tk.Text(root, bg=FIELD, fg=FG, relief="flat", height=6, wrap="none",
                           font=("Consolas", 10), padx=px(10), pady=px(8), cursor="arrow",
                           highlightthickness=0, takefocus=0, spacing1=px(2), spacing3=px(2))
        self.log.pack(fill="both", expand=True, padx=px(12), pady=(0, 0))
        self.log.tag_configure("time", foreground=MUTED)
        self.log.tag_configure("cat", foreground=RED)
        self.log.tag_configure("other", foreground=GOLD)
        self.log.tag_configure("keys", foreground=MUTED)

        self._place_window()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()
        self.root.after(5 * 60 * 1000, self.rehook)

    # -- actions --
    def toggle(self):
        self.filt.set_enabled(not self.filt.enabled)
        self.onoff.configure_button("Turn off" if self.filt.enabled else "Turn on",
                                    primary=not self.filt.enabled)
        self.tick(once=True)

    def toggle_startup(self):
        try:
            shortcuts.set_start_with_windows(not shortcuts.starts_with_windows())
        except Exception:
            pass
        self._show_startup()

    def _show_startup(self):
        on = shortcuts.starts_with_windows()
        self.startup.configure_button(("Starts with Windows  ✓" if on
                                       else "Start with Windows"))

    # -- bad shortcuts window --
    def open_options(self):
        if self.opt_win is not None and self.opt_win.winfo_exists():
            self.opt_win.deiconify()
            self.opt_win.lift()
            return
        w = self.opt_win = tk.Toplevel(self.root, bg=BG)
        w.withdraw()                 # shown once it is placed
        w.title("Cat Lock - bad shortcuts")
        w.resizable(False, False)
        try:
            w.iconbitmap(str(HERE / "icon.ico"))
        except tk.TclError:
            pass
        tk.Label(w, text="Ticked items are switched on", bg=BG, fg=MUTED,
                 font=UI_FONT).pack(anchor="w", padx=16, pady=(12, 0))
        cols = tk.Frame(w, bg=BG)
        cols.pack(fill="both", padx=8)
        self.opt_vars = {}
        for groups in (["Windows key"], ["Typing rules", "Ctrl and Alt", "Single keys"]):
            col = tk.Frame(cols, bg=BG)
            col.pack(side="left", anchor="n", padx=8)
            for group in groups:
                tk.Label(col, text=group.upper(), bg=BG, fg=GOLD,
                         font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(10, 2))
                for oid, g, label, _on, _combos in catfilter.BAD_KEYS:
                    if g != group:
                        continue
                    var = self.opt_vars[oid] = tk.BooleanVar(value=self.filt.options[oid])
                    tk.Checkbutton(col, text=label, variable=var, command=lambda o=oid: self.set_option(o),
                                   bg=BG, fg=FG, activebackground=BG, activeforeground=FG,
                                   selectcolor=FIELD, font=UI_FONT, anchor="w", bd=0,
                                   highlightthickness=0, cursor="hand2", padx=2, pady=1).pack(anchor="w")
        bottom = tk.Frame(w, bg=BG)
        bottom.pack(fill="x", padx=16, pady=(12, 14))
        RoundButton(bottom, "Recommended", self.reset_options, width=130).pack(side="left")
        RoundButton(bottom, "Close", w.destroy, width=90, primary=True).pack(side="right")
        w.update_idletasks()
        x = self.root.winfo_x() + self.root.winfo_width() + px(8)   # beside the main window
        if x + w.winfo_reqwidth() > self.root.winfo_vrootx() + user32.GetSystemMetrics(78):
            x = max(0, self.root.winfo_x() - w.winfo_reqwidth() - px(8))
        w.geometry(f"+{x}+{max(0, self.root.winfo_y())}")
        w.deiconify()

    def set_option(self, oid):
        self.filt.options[oid] = self.opt_vars[oid].get()
        self._save_settings()

    def reset_options(self):
        self.filt.options.update(catfilter.DEFAULT_OPTIONS)
        for oid, var in self.opt_vars.items():
            var.set(self.filt.options[oid])
        self._save_settings()

    def rehook(self):
        self.hook.post(WM_APP_REHOOK)
        self.root.after(5 * 60 * 1000, self.rehook)

    def close(self):
        """The X button: hide in the tray and keep watching."""
        if not self.tray.hwnd:
            self.quit()
            return
        self._save_settings()
        self.root.withdraw()
        if not self.told_about_tray:
            self.told_about_tray = True
            self.tray.balloon("Still watching. Click the cat by the clock to open.")

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit(self):
        self.quitting = True
        self._save_settings()
        self.tray.remove()
        self.hook.post(WM_QUIT)
        self.root.destroy()

    def do_command(self, cmd):
        if cmd == "show_hide":
            if self.root.state() == "normal":
                self.root.withdraw()
            else:
                self.show()
        elif cmd == "show":
            self.show()
        elif cmd == "toggle":
            self.toggle()
        elif cmd == "options":
            self.show()
            self.open_options()
        elif cmd == "quit":
            self.quit()

    # -- live display, 10 times a second --
    def tick(self, once=False):
        try:
            self._update(once)
        except Exception:
            pass                                  # never let one bad draw stop the loop
        if not once and not self.quitting:
            self.root.after(100, self.tick)

    def _update(self, once):
        while not once:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                break
            self.do_command(cmd)
            if cmd == "quit":
                return
        if not self.hook.hook:
            state = "fail"
        elif not self.filt.enabled:
            state = "off"
        else:
            state = "cat" if self.filt.cat_mode(now()) else "watch"
        if state != self.state:
            self.state = state
            self._draw_card()
            self.tray.show_state(state, self.filt.enabled)
        if self.filt.changes != self.shown_changes:
            self.shown_changes = self.filt.changes
            self._draw_tiles()
            self._show_log()

    # -- drawing --
    def _draw_header(self):
        c = self.header
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        x = w - px(26)
        step = 0
        while x > px(250):                         # paw prints walking in from the right
            paw(c, x, h / 2 + (px(-8) if step % 2 else px(8)), px(15), TRAIL)
            x -= px(30)
            step += 1
        c.create_image(px(12), h / 2, image=self.art["head"], anchor="w")
        c.create_text(px(50), h / 2, text="CAT LOCK", anchor="w", fill=FG, font=("Segoe UI Black", 12))
        c.create_text(px(148), h / 2 + px(1), text="paws off the keys", anchor="w", fill=MUTED, font=UI_FONT)

    def _draw_card(self):
        if self.state is None:
            return
        c = self.card
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        head, small, bg, fg, small_fg, picture = STATES[self.state]
        round_rect(c, 0, 0, w, h, px(14), fill=bg, outline=bg)
        c.create_image(px(12), h / 2, image=self.art["card_" + picture], anchor="w")
        c.create_text(px(104), h / 2 - px(11), text=head, anchor="w", fill=fg, font=("Segoe UI Semibold", 15))
        c.create_text(px(105), h / 2 + px(16), text=small, anchor="w", fill=small_fg, font=UI_FONT)

    def _draw_tiles(self):
        values = (self.filt.blocked, self.filt.cat_visits)
        for (c, icon, label), value in zip(self.tiles, values):
            c.delete("all")
            w, h = c.winfo_width(), c.winfo_height()
            round_rect(c, 0, 0, w, h, px(12), fill=PANEL, outline=PANEL)
            cx, cy = px(30), h / 2
            if icon == "key":                       # a blue keycap
                round_rect(c, cx - px(14), cy - px(13), cx + px(14), cy + px(15), px(7), fill="#1b5fa8", outline="")
                round_rect(c, cx - px(14), cy - px(15), cx + px(14), cy + px(11), px(7), fill=BLUE, outline="")
                c.create_text(cx, cy - px(2), text="A", fill="white", font=("Segoe UI", 9, "bold"))
            else:
                paw(c, cx, cy, px(28), GOLD)
            c.create_text(px(56), cy - px(1), text=f"{value:,}", anchor="w", fill=FG,
                          font=("Segoe UI Semibold", 16))
            c.create_text(w - px(14), cy, text=label, anchor="e", fill=MUTED, font=UI_FONT)

    def _show_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        items = list(self.filt.incidents)[::-1]
        if not items:
            self.log.insert("end", "All quiet. Nothing blocked yet.", "time")
        for inc in items:
            n = inc["count"]
            what = catfilter.KINDS[inc["kind"]]
            cat = inc["kind"] == "cat"
            paw_img = self.art["paw_red" if cat else "paw_gold"]
            if paw_img:
                self.log.image_create("end", image=paw_img, padx=px(2))
            self.log.insert("end", "  " + inc["when"] + "  ", "time")
            self.log.insert("end", f"{what:<19}", "cat" if cat else "other")
            self.log.insert("end", f"{n:>4} key{'s' if n != 1 else ' '}  ")
            self.log.insert("end", " ".join(inc["keys"]) + "\n", "keys")
        self.log.configure(state="disabled")

    # -- remember where the window was and the ticked shortcuts --
    def _load_settings(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        if not isinstance(data.get("options"), dict):
            data["options"] = {}
        return data

    def _place_window(self):
        try:
            x, y = int(self.settings["x"]), int(self.settings["y"])
            vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
            vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
            if not (vx - 50 <= x < vx + vw - 150 and vy - 20 <= y < vy + vh - 150):
                raise ValueError
            self.root.geometry(f"{px(440)}x{px(470)}+{x}+{y}")
        except Exception:
            self.root.geometry(f"{px(440)}x{px(470)}")

    def _save_settings(self):
        try:
            if self.root.state() == "normal":
                x, y = self.root.geometry().split("+")[1:3]
                self.settings.update(x=int(x), y=int(y))
            self.settings["options"] = dict(self.filt.options)
            tmp = SETTINGS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.settings), encoding="utf-8")
            os.replace(tmp, SETTINGS_FILE)        # all or nothing, even if the PC dies mid-save
        except Exception:
            pass


def main():
    # one copy only: a second one would just double up the blocking
    kernel32.CreateMutexW(None, False, "CatLock-single-instance")
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS: open the one already running
        other = user32.FindWindowW("CatLockTray", None)
        if other:
            user32.PostMessageW(other, WM_SHOW_APP, 0, 0)
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # sharp text on scaled screens
    except Exception:
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CatLock.App")
    except Exception:
        pass
    filt = catfilter.CatFilter(really_down=key_is_down, lock_on=lock_is_on)
    hook = KeyboardHook(filt)
    hook.start()
    commands = queue.Queue()
    tray = TrayIcon(commands)
    tray.start()
    tray.ready.wait(3)
    root = tk.Tk()
    CatLockApp(root, filt, hook, tray, commands)
    if "--min" in sys.argv:
        if tray.hwnd:
            root.withdraw()      # just the cat by the clock
        else:
            root.iconify()
    root.mainloop()


if __name__ == "__main__":
    main()
