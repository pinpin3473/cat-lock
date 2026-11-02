"""Makes and removes the Cat Lock shortcuts (Desktop and Start with Windows).

Run on its own to (re)make the Desktop shortcut:  python shortcuts.py
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE / "cat_lock.pyw"
ICON = HERE / "icon.ico"
STARTUP_LNK = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup\Cat Lock.lnk"
DESKTOP_LNK = Path(os.environ["USERPROFILE"]) / "Desktop" / "Cat Lock.lnk"


def pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def ps_text(value):
    """A PowerShell string that stays plain text whatever is in it (e.g. O'Brien)."""
    return "'" + str(value).replace("'", "''") + "'"


def make_shortcut(lnk, minimized=False):
    args = f'"{APP}"' + (" --min" if minimized else "")
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({ps_text(lnk)});"
          f"$s.TargetPath={ps_text(pythonw())};$s.Arguments={ps_text(args)};"
          f"$s.WorkingDirectory={ps_text(HERE)};$s.IconLocation={ps_text(str(ICON) + ',0')};"
          f"$s.Description='Cat Lock - stops the cat typing';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   creationflags=0x08000000)   # CREATE_NO_WINDOW


def starts_with_windows():
    return STARTUP_LNK.exists()


def set_start_with_windows(on):
    if on:
        make_shortcut(STARTUP_LNK, minimized=True)
    elif STARTUP_LNK.exists():
        STARTUP_LNK.unlink()


if __name__ == "__main__":
    make_shortcut(DESKTOP_LNK)
    print("Made", DESKTOP_LNK)
