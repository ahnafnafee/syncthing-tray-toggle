"""Manage a Start Menu \\ Startup shortcut so the tray launches at login.

A Startup-folder ``.lnk`` is preferred over an ``HKCU\\...\\Run`` registry value:
it is visible and toggleable in Task Manager's Startup tab, needs no registry
write, and is trivially idempotent (one file).

Usable two ways:
    * from the tray's "Start on login" menu item (``install`` / ``uninstall``);
    * standalone before the tray exists: ``pythonw autostart.py --install``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "Syncthing Tray Toggle.lnk"
ENTRY_SCRIPT = "syncthing_tray.pyw"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _startup_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return _startup_dir() / SHORTCUT_NAME


def is_installed() -> bool:
    return shortcut_path().exists()


def _target() -> tuple[str, str, str]:
    """Return (target_exe, arguments, working_dir) for the shortcut."""
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


def install() -> Path:
    target, arguments, workdir = _target()
    lnk = shortcut_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{_ps_quote(str(lnk))}'); "
        f"$s.TargetPath = '{_ps_quote(target)}'; "
        f"$s.Arguments = '{_ps_quote(arguments)}'; "
        f"$s.WorkingDirectory = '{_ps_quote(workdir)}'; "
        f"$s.IconLocation = '{_ps_quote(target)}'; "
        "$s.WindowStyle = 7; "
        "$s.Description = 'Syncthing read-only / read-write tray toggle'; "
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


def uninstall() -> None:
    shortcut_path().unlink(missing_ok=True)


def toggle() -> bool:
    """Flip the autostart state. Returns True if now installed."""
    if is_installed():
        uninstall()
        return False
    install()
    return True


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Manage the login shortcut for Syncthing Tray Toggle.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="create the Startup shortcut")
    group.add_argument("--uninstall", action="store_true", help="remove the Startup shortcut")
    group.add_argument("--status", action="store_true", help="report whether it is installed")
    args = parser.parse_args(argv)

    if args.install:
        print(f"Installed: {install()}")
    elif args.uninstall:
        uninstall()
        print("Uninstalled.")
    else:
        print("Installed" if is_installed() else "Not installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
