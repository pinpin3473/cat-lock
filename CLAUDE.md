# Cat Lock

Stops the cat typing when he walks on the keyboard. Built 2 Nov 2026.
Desktop shortcut: **Cat Lock** (pythonw, no console). The window's
"Start with Windows" button adds/removes a shortcut in the Startup folder
that starts it minimised (`--min`).

## Files
- `cat_lock.pyw` - window + Windows low-level keyboard hook (ctypes only, no
  extra packages). Hook runs on its own thread; it is re-made every 5 minutes
  because Windows silently drops a hook that is ever too slow.
- `catfilter.py` - the rules, no Windows calls. Settings at the top
  (PAW_S, LEAN_S, QUIET_S, SAME_GAP_S, TRIPLE_OK).
- `test_catfilter.py` - `python test_catfilter.py` (33 tests).
- `test_stress.py` - random key storms (2M events default), checks no key is
  ever left stuck down in Windows. Found 2 stuck-key bugs on 2 Nov 2026
  (Turn off / Turn on while a key was held), both fixed + regression tests.
- `shortcuts.py` - `python shortcuts.py` remakes the Desktop shortcut.
- `make_art.py` - draws ALL the artwork, a white cat asleep on a keyboard:
  icon.ico (cat on a charcoal tile: window, taskbar, shortcuts), tray_watch /
  tray_cat / tray_off.ico, and art\*.png (status-card cat, header cat, log paws)
  pre-drawn for each Windows zoom 100-300%. tray_preview.png to check by eye.
  Re-run it after changing the drawing, then `python shortcuts.py`.

## Look (2 Nov 2026)
Header with sleeping cat + faint paw-print trail; status card shows the cat
(asleep = watching, eyes open on red = cat mode, grey = off); two tiles (blue
keycap = keys blocked, gold paw = cat visits); paw bullets in the log.

## Tray (added 2 Nov 2026)
TrayIcon thread in cat_lock.pyw (Shell_NotifyIcon via ctypes, own message loop).
Left-click shows/hides the window; right-click menu: Show, Turn off/on, Bad
shortcuts, Quit (dark menu via uxtheme ordinal 135). Clicks go to the window
through a queue polled every 100 ms. The X button hides to the tray (one balloon
per run); --min (Startup shortcut) starts hidden in the tray. Windows 11 puts new
tray icons behind the ^ arrow until the user switches them on in Settings.
- `cat_lock_settings.json` - window position + ticked bad shortcuts.

## Rules (see catfilter.py docstring)
1. Held character key types once (Backspace, Delete, arrows, Home/End,
   PgUp/PgDn, volume still repeat; Ctrl/Alt/Win shortcuts still repeat).
2. Second key within 30 ms of another = paw, dropped. Normal rollover typing
   (keys 40+ ms apart) passes.
3. Three keys within 30 ms, a key pressed while another is held 0.5 s+, or two
   keys held together = cat mode: everything blocked until 1 s of quiet.
4. Third press of the same letter within 2 s each is dropped - not W (www)
   and not I (Joao III). Digits are never limited.
5. Bad shortcuts (added 2 Nov 2026): BAD_KEYS list in catfilter.py, each ticked
   on/off in the "Bad shortcuts" window (saved in cat_lock_settings.json,
   "Recommended" restores the defaults). Plus "paw": Ctrl/Alt/Win + key
   going down within 30 ms. When a block happens with Win or Alt held, the
   Win/Alt key-up is swallowed and re-sent after a dummy key (0xE8), so the
   Start menu / menu bar doesn't open. Win+L and Ctrl+Alt+Del can't be blocked
   by any app. Sticky Keys (Shift x5) / Filter Keys (hold Shift 8 s) are best
   switched off in Windows Settings > Accessibility > Keyboard.
Modifiers never blocked unless ticked. Software-typed keys (on-screen keyboard, etc.) ignored.
Nothing typed is saved anywhere; the log in the window is memory only.

## Testing
Never drive it with synthetic keystrokes: injected keys are ignored by the
hook anyway, and they land in the chat box. Exec the .pyw with a patched
`Tk.mainloop`, feed `app.filt.on_key(...)` directly (set
`filt.really_down = lambda vk: True` first), and screenshot the window.

## Pre-GitHub review (2 Nov 2026)
Fixed: stuck keys when toggled mid-hold; Win/Alt replay now uses SendInput and
falls back to the real key-up if Windows refuses; display loop can't die;
settings validated + written atomically; missing art tolerated; second copy
shows the first; PowerShell quoting in shortcuts.py; typing rules switchable;
tray thread exits on Quit. A Windows-level stress (hook proc 200k calls ~4 us,
300 re-hooks, 9 s cross-thread storm, leaks, bad settings) passed 20/20; that
script was kept out of the repo (in the Claude session scratchpad).
