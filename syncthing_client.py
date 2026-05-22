"""Minimal Syncthing REST API client built on the standard library.

Only the handful of endpoints this app needs, with a small exception taxonomy
so the tray can react to "not running" vs "bad key" vs "folder gone" without
parsing strings.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

# Folder types we toggle between (Syncthing's exact config values).
READ_ONLY = "receiveonly"
READ_WRITE = "sendreceive"


class SyncthingError(Exception):
    """Base error for a Syncthing API call."""


class SyncthingUnreachable(SyncthingError):
    """Network-level failure: Syncthing not running, refused, or timed out."""


class SyncthingAuthError(SyncthingError):
    """HTTP 403 — missing or wrong API key."""


class FolderNotFound(SyncthingError):
    """HTTP 404 — the folder id does not exist."""


class SyncthingClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 8.0,
        verify_tls: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._ssl_ctx: ssl.SSLContext | None = None
        if not verify_tls and self.base_url.lower().startswith("https"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ssl_ctx = ctx

    def _call(self, method: str, path: str, *, body=None, timeout: float | None = None):
        headers = {"X-API-Key": self.api_key}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif method in ("POST", "PATCH", "PUT"):
            # Force an (empty) body so urllib sends Content-Length and the
            # intended method rather than silently downgrading to GET.
            data = b""
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(
                req, timeout=timeout or self.timeout, context=self._ssl_ctx
            ) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:  # subclass of URLError — catch first
            if exc.code == 403:
                raise SyncthingAuthError("HTTP 403 — check the API key") from exc
            if exc.code == 404:
                raise FolderNotFound(f"HTTP 404 — {path}") from exc
            raise SyncthingError(f"HTTP {exc.code} — {path}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SyncthingUnreachable(str(exc)) from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _folder_query(folder_id: str) -> str:
        return urllib.parse.urlencode({"folder": folder_id})

    # --- system -----------------------------------------------------------
    def version(self):
        return self._call("GET", "/rest/system/version")

    def system_status(self):
        return self._call("GET", "/rest/system/status")

    def restart_required(self) -> bool:
        data = self._call("GET", "/rest/config/restart-required")
        return bool(data and data.get("requiresRestart"))

    # --- config -----------------------------------------------------------
    def get_folders(self) -> list[dict]:
        return self._call("GET", "/rest/config/folders") or []

    def get_folder(self, folder_id: str):
        fid = urllib.parse.quote(folder_id, safe="")
        return self._call("GET", f"/rest/config/folders/{fid}")

    def set_folder_type(self, folder_id: str, folder_type: str):
        """PATCH only the ``type`` field; other folder settings are untouched."""
        fid = urllib.parse.quote(folder_id, safe="")
        return self._call("PATCH", f"/rest/config/folders/{fid}", body={"type": folder_type})

    # --- db ---------------------------------------------------------------
    def scan(self, folder_id: str, *, timeout: float | None = 600.0):
        """Trigger a rescan. Blocks server-side until the scan completes (can be
        many seconds for large folders), so callers should run this off the UI
        thread. The scan continues server-side even if this call times out."""
        return self._call(
            "POST", f"/rest/db/scan?{self._folder_query(folder_id)}", timeout=timeout
        )

    def revert(self, folder_id: str):
        """Discard local changes in a receive-only folder (DESTRUCTIVE)."""
        return self._call("POST", f"/rest/db/revert?{self._folder_query(folder_id)}")

    def folder_status(self, folder_id: str):
        """Sync state. Expensive per Syncthing docs — call sparingly."""
        return self._call("GET", f"/rest/db/status?{self._folder_query(folder_id)}")
