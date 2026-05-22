"""The tray application: pystray wiring, polling, and the toggle actions.

Threading model
---------------
* The main thread runs ``icon.run()`` (the Win32 message loop). It is never
  blocked by us.
* ``setup=`` runs once on its own thread: it does an immediate refresh and
  starts the poll thread.
* One daemon poll thread refreshes folder state every ``poll_interval`` seconds
  via the cheap ``GET /rest/config/folders`` endpoint.
* Menu clicks run on pystray's thread; any network work they trigger is handed
  to a short-lived daemon thread so the UI never stalls (a scan can block
  server-side for a long time on a large folder).

Mutating ``icon.icon`` / ``icon.title`` and calling ``icon.update_menu()`` are
thread-safe on the Win32 backend.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import webbrowser
from dataclasses import dataclass

import pystray
from pystray import Menu, MenuItem

import autostart
import icons
from config import AppConfig
from syncthing_client import (
    READ_ONLY,
    READ_WRITE,
    SyncthingClient,
    SyncthingAuthError,
    SyncthingError,
    SyncthingUnreachable,
)

log = logging.getLogger(__name__)

# MessageBoxW flags for the destructive-revert confirmation.
_MB_YESNO = 0x4
_MB_ICONWARNING = 0x30
_MB_DEFBUTTON2 = 0x100  # default the focus to "No"
_MB_TOPMOST = 0x40000
_IDYES = 6


@dataclass
class FolderState:
    id: str
    label: str
    type: str
    fs_watcher: bool = True

    @property
    def writable(self) -> bool:
        return self.type == READ_WRITE


class TrayApp:
    def __init__(self, client: SyncthingClient, cfg: AppConfig) -> None:
        self.client = client
        self.cfg = cfg
        self._lock = threading.Lock()
        self._folders: list[FolderState] = []
        self._primary_id: str | None = cfg.primary_folder
        self._reachable = False
        self._hint = "starting…"
        self._syncing = False
        self._stop = threading.Event()
        self._poll_count = 0
        self._revert_timers: dict[str, threading.Timer] = {}
        self._menu_sig: tuple | None = None
        self._prev_reachable: bool | None = None
        self.icon = pystray.Icon(
            "syncthing-tray-toggle",
            icon=icons.make_icon(icons.UNREACHABLE),
            title="Syncthing Tray Toggle — starting…",
            menu=self._build_menu(),
        )

    # -- lifecycle ---------------------------------------------------------
    def run(self) -> None:
        self.icon.run(setup=self._on_setup)

    def _on_setup(self, icon: pystray.Icon) -> None:
        icon.visible = True
        self._refresh_once()
        if self.cfg.reset_to_readonly_on_startup and self._reachable:
            self._enforce_readonly_startup()
        self._apply_state()
        log.info("tray ready: api_url=%s reachable=%s folders=%d",
                 self.cfg.api_url, self._reachable, len(self._folders))
        threading.Thread(target=self._poll_loop, name="poll", daemon=True).start()

    def _poll_loop(self) -> None:
        # The first refresh already happened in setup; wait, then loop.
        while not self._stop.wait(self.cfg.poll_interval):
            try:
                self._refresh_once()
                self._apply_state()
            except Exception:  # never let the poll thread die
                log.exception("poll iteration failed")

    def _on_quit(self, icon: pystray.Icon, item) -> None:
        self._stop.set()
        for timer in list(self._revert_timers.values()):
            timer.cancel()
        icon.visible = False
        icon.stop()

    # -- state -------------------------------------------------------------
    def _is_managed(self, fid: str) -> bool:
        return self.cfg.managed_folders is None or fid in self.cfg.managed_folders

    def _refresh_once(self) -> None:
        self._poll_count += 1
        if not self.cfg.api_key:
            self._set_unreachable("API key not found — is Syncthing installed?")
            return
        try:
            raw = self.client.get_folders()
        except SyncthingAuthError:
            self._set_unreachable("Auth failed (403) — check API key")
            return
        except SyncthingUnreachable:
            self._set_unreachable("Syncthing unreachable")
            return
        except SyncthingError as exc:
            self._set_unreachable(f"API error: {exc}")
            return

        folders = [
            FolderState(
                id=f.get("id", ""),
                label=f.get("label") or f.get("id", ""),
                type=f.get("type", ""),
                fs_watcher=bool(f.get("fsWatcherEnabled", True)),
            )
            for f in raw
            if self._is_managed(f.get("id", ""))
        ]
        primary = self._primary_id
        if primary is None or not any(f.id == primary for f in folders):
            primary = folders[0].id if folders else None

        syncing = self._syncing
        if folders and self._poll_count % 6 == 1:  # probe the expensive status rarely
            syncing = self._probe_syncing(primary)

        with self._lock:
            self._folders = folders
            self._primary_id = primary
            self._reachable = True
            self._syncing = syncing
            self._hint = self._compose_hint(folders, syncing)
        self._note_reachable(True, f"{len(folders)} folder(s)")

    def _probe_syncing(self, primary: str | None) -> bool:
        if not primary:
            return False
        try:
            st = self.client.folder_status(primary)
        except SyncthingError:
            return False
        return bool(st and st.get("state") not in ("idle", "", None))

    def _set_unreachable(self, hint: str) -> None:
        with self._lock:
            self._reachable = False
            self._hint = hint
        self._note_reachable(False, hint)

    def _note_reachable(self, reachable: bool, detail: str) -> None:
        if reachable != self._prev_reachable:
            self._prev_reachable = reachable
            if reachable:
                log.info("connected to Syncthing — %s", detail)
            else:
                log.warning("Syncthing unreachable — %s", detail)

    def _compose_hint(self, folders: list[FolderState], syncing: bool) -> str:
        if not folders:
            return "No managed folders"
        suffix = " · syncing" if syncing else ""
        if len(folders) == 1:
            f = folders[0]
            return f"{f.label}: {'writable' if f.writable else 'read-only'}{suffix}"
        writable = sum(1 for f in folders if f.writable)
        return f"{len(folders)} folders · {writable} writable{suffix}"

    def _snapshot(self) -> tuple[list[FolderState], str | None, bool, str, bool]:
        with self._lock:
            return (
                list(self._folders),
                self._primary_id,
                self._reachable,
                self._hint,
                self._syncing,
            )

    def _get_folder(self, fid: str | None) -> FolderState | None:
        if not fid:
            return None
        with self._lock:
            for f in self._folders:
                if f.id == fid:
                    return f
        return None

    # -- icon / menu -------------------------------------------------------
    def _icon_state(self, folders: list[FolderState], reachable: bool) -> str:
        if not reachable:
            return icons.UNREACHABLE
        if not folders:
            return icons.READ_ONLY
        return icons.WRITABLE if any(f.writable for f in folders) else icons.READ_ONLY

    def _apply_state(self) -> None:
        folders, primary, reachable, hint, syncing = self._snapshot()
        self.icon.icon = icons.make_icon(
            self._icon_state(folders, reachable), syncing and reachable
        )
        self.icon.title = f"Syncthing: {hint}"
        sig = (tuple(f.id for f in folders), primary, reachable)
        if sig != self._menu_sig:
            self._menu_sig = sig
            self.icon.menu = self._build_menu()
        self.icon.update_menu()

    def _build_menu(self) -> Menu:
        folders, primary, reachable, _, _ = self._snapshot()
        items: list[MenuItem] = []
        if not reachable:
            items += [
                MenuItem(lambda it: self._snapshot()[3], None, enabled=lambda it: False),
                Menu.SEPARATOR,
            ]
        for f in folders:
            fid = f.id
            items.append(
                MenuItem(
                    self._folder_text(fid),
                    self._folder_action(fid),
                    checked=self._folder_checked(fid),
                    default=(fid == primary),
                )
            )
        if folders:
            items += [
                Menu.SEPARATOR,
                MenuItem("Force rescan", lambda i, it: self._spawn(self._kick_scan, self._primary_id)),
                MenuItem(
                    "Revert local changes…",
                    lambda i, it: self._spawn(self._confirm_revert, self._primary_id),
                    enabled=lambda it: self._can_revert(),
                ),
            ]
        items += [
            Menu.SEPARATOR,
            MenuItem("Open Syncthing GUI", lambda i, it: webbrowser.open(self.cfg.api_url)),
            MenuItem("Refresh now", lambda i, it: self._spawn(self._refresh_and_apply)),
            MenuItem(
                "Start on login",
                lambda i, it: self._toggle_autostart(),
                checked=lambda it: autostart.is_installed(),
            ),
            Menu.SEPARATOR,
            MenuItem("Quit", self._on_quit),
        ]
        return Menu(*items)

    def _folder_text(self, fid: str):
        def text(item) -> str:
            f = self._get_folder(fid)
            if f is None:
                return f"{fid}: (removed)"
            return f"{f.label}: {'WRITABLE' if f.writable else 'read-only'}"
        return text

    def _folder_checked(self, fid: str):
        return lambda item: bool((f := self._get_folder(fid)) and f.writable)

    def _folder_action(self, fid: str):
        return lambda icon, item: self._spawn(self._toggle_folder, fid)

    def _can_revert(self) -> bool:
        f = self._get_folder(self._primary_id)
        return bool(f and not f.writable)

    # -- actions -----------------------------------------------------------
    @staticmethod
    def _spawn(fn, *args) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _toggle_folder(self, fid: str) -> None:
        f = self._get_folder(fid)
        if f is None:
            return
        new_type = READ_ONLY if f.writable else READ_WRITE
        try:
            self.client.set_folder_type(fid, new_type)
        except SyncthingError as exc:
            log.error("toggle failed for %s: %s", fid, exc)
            self._refresh_and_apply()
            return
        log.info("set folder %s -> %s", fid, new_type)

        if new_type == READ_WRITE:
            self._arm_auto_revert(fid)
            # With the filesystem watcher on, local changes are already indexed
            # and propagate immediately; only nudge a scan when it is off.
            if not f.fs_watcher:
                self._spawn(self._kick_scan, fid)
        else:
            self._cancel_auto_revert(fid)

        with self._lock:
            for ff in self._folders:
                if ff.id == fid:
                    ff.type = new_type
            self._hint = self._compose_hint(self._folders, self._syncing)
        self._apply_state()

    def _kick_scan(self, fid: str | None) -> None:
        if not fid:
            return
        with self._lock:
            self._syncing = True
        self._apply_state()
        try:
            self.client.scan(fid)
            log.info("rescan complete for %s", fid)
        except SyncthingError as exc:
            log.warning("rescan for %s ended: %s", fid, exc)
        self._refresh_and_apply()

    def _confirm_revert(self, fid: str | None) -> None:
        f = self._get_folder(fid)
        if f is None:
            return
        text = (
            f"Revert local changes in '{f.label}'?\n\n"
            "This DISCARDS local modifications and restores the cluster's "
            "version of any changed files. It cannot be undone."
        )
        res = ctypes.windll.user32.MessageBoxW(
            0, text, "Syncthing Tray Toggle — Revert",
            _MB_YESNO | _MB_ICONWARNING | _MB_DEFBUTTON2 | _MB_TOPMOST,
        )
        if res == _IDYES:
            try:
                self.client.revert(fid)
                log.info("reverted local changes in %s", fid)
            except SyncthingError as exc:
                log.error("revert failed for %s: %s", fid, exc)
        self._refresh_and_apply()

    def _refresh_and_apply(self) -> None:
        self._refresh_once()
        self._apply_state()

    def _toggle_autostart(self) -> None:
        try:
            on = autostart.toggle()
            log.info("autostart %s", "enabled" if on else "disabled")
        except Exception as exc:  # subprocess / COM failure
            log.error("autostart toggle failed: %s", exc)
        self.icon.update_menu()

    def _enforce_readonly_startup(self) -> None:
        for f in list(self._folders):
            if f.writable:
                try:
                    self.client.set_folder_type(f.id, READ_ONLY)
                    f.type = READ_ONLY
                    log.info("startup: forced %s to read-only", f.id)
                except SyncthingError as exc:
                    log.warning("startup read-only enforce failed for %s: %s", f.id, exc)

    # -- auto-revert safeguard (off unless auto_revert_after_minutes > 0) ---
    def _arm_auto_revert(self, fid: str) -> None:
        minutes = self.cfg.auto_revert_after_minutes
        if minutes and minutes > 0:
            self._cancel_auto_revert(fid)
            timer = threading.Timer(minutes * 60, self._auto_revert_fire, args=(fid,))
            timer.daemon = True
            timer.start()
            self._revert_timers[fid] = timer

    def _cancel_auto_revert(self, fid: str) -> None:
        timer = self._revert_timers.pop(fid, None)
        if timer:
            timer.cancel()

    def _auto_revert_fire(self, fid: str) -> None:
        f = self._get_folder(fid)
        if f and f.writable:
            log.info("auto-revert timer: returning %s to read-only", fid)
            self._toggle_folder(fid)
