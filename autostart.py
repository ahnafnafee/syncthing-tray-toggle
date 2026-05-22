"""Windows shortcut management for Syncthing Tray Toggle.

Two kinds of shortcut, both pointing at the venv's ``pythonw.exe`` so they run
with no console window and with the dependencies available:

* a **login** shortcut in the Startup folder (``install`` / ``uninstall``);
* a **launcher** shortcut you can double-click, on the Desktop or in the
  project folder (``make_launcher``).

Usable from the tray's "Start on login" menu item, or standalone:

    python autostart.py --install       # run at login
    python autostart.py --desktop        # double-click launcher on the Desktop
    python autostart.py --here           # double-click launcher in this folder

Run the CLI with ``python`` (not ``pythonw``) so the printed output is visible.
"""
from __future__ import annotations

import os
import subprocess
import sys
import winreg
from pathlib import Path

SHORTCUT_NAME = "Syncthing Tray Toggle.lnk"
ENTRY_SCRIPT = "syncthing_tray.pyw"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _startup_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def desktop_dir() -> Path:
    """The real Desktop path, honoring OneDrive/known-folder redirection."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        return Path(os.path.expandvars(value))
    except OSError:
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def shortcut_path() -> Path:
    return _startup_dir() / SHORTCUT_NAME


def is_installed() -> bool:
    return shortcut_path().exists()


def _target() -> tuple[str, str, str]:
    """Return (target_exe, arguments, working_dir) for a shortcut."""
    here = Path(__file__).resolve().parent
    if getattr(sys, "frozen", False):
        # Packaged single-file .exe: launch it directly, no script argument.
        exe = sys.executable
        return exe, "", str(Path(exe).parent)
    # Source mode: run the .pyw with pythonw.exe so there is no console window.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        import shutil

        found = shutil.which("pythonw")
        pythonw = Path(found) if found else Path(sys.executable)
    return str(pythonw), f'"{here / ENTRY_SCRIPT}"', str(here)


def _ps_quote(value: str) -> str:
    """Escape a value for a single-quoted PowerShell string."""
    return value.replace("'", "''")


def _write_shortcut(lnk: Path, description: str) -> Path:
    target, arguments, workdir = _target()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{_ps_quote(str(lnk))}'); "
        f"$s.TargetPath = '{_ps_quote(target)}'; "
        f"$s.Arguments = '{_ps_quote(arguments)}'; "
        f"$s.WorkingDirectory = '{_ps_quote(workdir)}'; "
        f"$s.IconLocation = '{_ps_quote(target)}'; "
        "$s.WindowStyle = 7; "
        f"$s.Description = '{_ps_quote(description)}'; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        creationflags=_CREATE_NO_WINDOW,
    )
    return lnk


def install() -> Path:
    return _write_shortcut(shortcut_path(), "Syncthing read-only / read-write tray toggle")


def uninstall() -> None:
    shortcut_path().unlink(missing_ok=True)


def toggle() -> bool:
    """Flip the login-autostart state. Returns True if now installed."""
    if is_installed():
        uninstall()
        return False
    install()
    return True


def make_launcher(dest_dir: Path | str) -> Path:
    """Create a double-click launcher shortcut in ``dest_dir``."""
    return _write_shortcut(Path(dest_dir) / SHORTCUT_NAME, "Launch Syncthing Tray Toggle")


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Create shortcuts for Syncthing Tray Toggle (run with python, not pythonw)."
    )
    parser.add_argument("--install", action="store_true", help="create the login (Startup) shortcut")
    parser.add_argument("--uninstall", action="store_true", help="remove the login shortcut")
    parser.add_argument("--status", action="store_true", help="report login-shortcut state")
    parser.add_argument("--desktop", action="store_true", help="create a double-click launcher on the Desktop")
    parser.add_argument("--here", action="store_true", help="create a double-click launcher in the project folder")
    args = parser.parse_args(argv)

    did = False
    if args.install:
        print(f"Login shortcut installed: {install()}")
        did = True
    if args.uninstall:
        uninstall()
        print("Login shortcut removed.")
        did = True
    if args.desktop:
        print(f"Desktop launcher created: {make_launcher(desktop_dir())}")
        did = True
    if args.here:
        print(f"Project launcher created: {make_launcher(Path(__file__).resolve().parent)}")
        did = True
    if args.status or not did:
        print("Login shortcut: " + ("installed" if is_installed() else "not installed"))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
