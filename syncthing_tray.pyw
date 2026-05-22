"""Entry point for Syncthing Tray Toggle.

Launch with ``pythonw.exe`` (or the bundled ``.exe``) for a console-less tray
app. Because ``pythonw`` has no stdout, all diagnostics go to a rotating log
file, and any startup failure is surfaced in a message box so the app never
"silently fails to appear".

If launched by the wrong interpreter (e.g. double-clicking the ``.pyw`` uses
whatever Python is associated with that extension, which usually lacks our
dependencies), the app relaunches itself with the project's ``.venv``
interpreter — see ``_reexec_into_venv_if_needed``.
"""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import sys
from pathlib import Path

APP_NAME = "Syncthing Tray Toggle"


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / "SyncthingTrayToggle"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _setup_logging() -> Path:
    logfile = _log_dir() / "app.log"
    handler = logging.handlers.RotatingFileHandler(
        logfile, maxBytes=512_000, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
    )
    return logfile


def _error_box(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, f"{APP_NAME} — Error", 0x10 | 0x40000)
    except Exception:
        pass


def _reexec_into_venv_if_needed() -> None:
    """Relaunch with the project's venv interpreter if our deps are missing.

    Makes double-clicking the ``.pyw`` work regardless of which Python the
    ``.pyw`` file association points at, as long as ``uv sync`` has created the
    ``.venv``. Guarded by an env var so it can only happen once.
    """
    import importlib.util

    if importlib.util.find_spec("pystray") is not None:
        return  # dependencies are importable — we're in the right interpreter
    if os.environ.get("STT_REEXEC") == "1":
        return  # already retried; fall through to a clear error message

    here = Path(__file__).resolve().parent
    venv_pythonw = here / ".venv" / "Scripts" / "pythonw.exe"
    try:
        already_here = venv_pythonw.resolve() == Path(sys.executable).resolve()
    except OSError:
        already_here = False
    if venv_pythonw.exists() and not already_here:
        import subprocess

        logging.info("deps missing under %s; relaunching via %s", sys.executable, venv_pythonw)
        subprocess.Popen(
            [str(venv_pythonw), str(Path(__file__).resolve())],
            cwd=str(here),
            env={**os.environ, "STT_REEXEC": "1"},
        )
        raise SystemExit(0)  # not caught by `except Exception` below


def main() -> int:
    logfile = _setup_logging()
    logging.info("starting %s (python=%s)", APP_NAME, sys.executable)
    try:
        _reexec_into_venv_if_needed()

        import config
        from syncthing_client import SyncthingClient
        from tray_icon import TrayApp

        cfg = config.load()
        if not cfg.is_complete:
            logging.warning(
                "incomplete config: api_url=%s api_key_set=%s", cfg.api_url, bool(cfg.api_key)
            )
        client = SyncthingClient(
            cfg.api_url, cfg.api_key, timeout=cfg.request_timeout, verify_tls=cfg.verify_tls
        )
        TrayApp(client, cfg).run()
        return 0
    except Exception as exc:  # noqa: BLE001 — last-resort guard for a GUI app
        logging.exception("fatal startup error")
        _error_box(
            f"{APP_NAME} failed to start:\n\n{exc}\n\n"
            f"If you haven't yet, run 'uv sync' in the project folder.\n\nLog: {logfile}"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
