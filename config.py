"""Configuration for Syncthing Tray Toggle.

Resolves the Syncthing REST API URL + key and app options. Precedence, highest
wins:

    1. An explicit ``config.toml`` next to this module.
    2. Environment variables (SYNCTHING_API_URL, SYNCTHING_API_KEY, ...).
    3. Auto-discovery from Syncthing's own ``config.xml``.
    4. Built-in defaults.

The API key is read from Syncthing's config at runtime, so it never has to live
in this project. ``config.toml`` is gitignored for the case where someone needs
to override the key or point at a remote/non-default instance.
"""
from __future__ import annotations

import os
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_API_URL = "http://127.0.0.1:8384"


@dataclass(frozen=True)
class AppConfig:
    api_url: str = DEFAULT_API_URL
    api_key: str = ""
    poll_interval: float = 10.0
    managed_folders: tuple[str, ...] | None = None  # None = manage every folder
    primary_folder: str | None = None               # left-click target; None = first
    reset_to_readonly_on_startup: bool = False       # safeguard (a) — OFF by default
    auto_revert_after_minutes: int = 0               # safeguard (b) — 0 = OFF
    request_timeout: float = 8.0
    verify_tls: bool = True

    @property
    def is_complete(self) -> bool:
        return bool(self.api_url and self.api_key)


def config_path() -> Path:
    return Path(__file__).resolve().parent / "config.toml"


def _candidate_xml_paths() -> list[Path]:
    paths: list[Path] = []
    # Explicit Syncthing config/home overrides take priority among XML sources.
    for env in ("STCONFDIR", "STHOMEDIR"):
        base = os.environ.get(env)
        if base:
            paths.append(Path(base) / "config.xml")
    for env in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env)
        if base:
            paths.append(Path(base) / "Syncthing" / "config.xml")
    return paths


def _normalize_address(address: str, tls: bool) -> str | None:
    address = address.strip()
    if not address:
        return None
    # A wildcard bind host is not a valid connect target; localhost reaches it.
    if address.startswith("0.0.0.0:"):
        address = "127.0.0.1:" + address.split(":", 1)[1]
    elif address.startswith(":"):
        address = "127.0.0.1" + address
    elif address.startswith("[::]:"):
        address = "127.0.0.1:" + address.split("]:", 1)[1]
    scheme = "https" if tls else "http"
    return f"{scheme}://{address}"


def discover_from_xml() -> tuple[str | None, str | None]:
    """Return (api_url, api_key) parsed from the first readable config.xml."""
    for path in _candidate_xml_paths():
        try:
            if not path.is_file():
                continue
            gui = ET.parse(path).getroot().find("gui")
            if gui is None:
                continue
            api_key = (gui.findtext("apikey") or "").strip() or None
            tls = (gui.get("tls") or "false").strip().lower() == "true"
            api_url = _normalize_address(gui.findtext("address") or "", tls)
            return api_url, api_key
        except (ET.ParseError, OSError):
            continue
    return None, None


def _env_overrides() -> dict:
    out: dict = {}
    if v := os.environ.get("SYNCTHING_API_URL"):
        out["api_url"] = v
    if v := os.environ.get("SYNCTHING_API_KEY"):
        out["api_key"] = v
    if v := os.environ.get("SYNCTHING_TRAY_POLL"):
        try:
            out["poll_interval"] = float(v)
        except ValueError:
            pass
    if v := os.environ.get("SYNCTHING_TRAY_FOLDERS"):
        folders = tuple(f.strip() for f in v.split(",") if f.strip())
        if folders:
            out["managed_folders"] = folders
    return out


def _toml_overrides(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out: dict = {}
    for key in ("api_url", "api_key", "primary_folder"):
        if isinstance(data.get(key), str):
            out[key] = data[key]
    for key in ("poll_interval", "request_timeout"):
        if key in data:
            try:
                out[key] = float(data[key])
            except (TypeError, ValueError):
                pass
    if "auto_revert_after_minutes" in data:
        try:
            out["auto_revert_after_minutes"] = int(data["auto_revert_after_minutes"])
        except (TypeError, ValueError):
            pass
    for key in ("verify_tls", "reset_to_readonly_on_startup"):
        if key in data:
            out[key] = bool(data[key])
    if isinstance(data.get("managed_folders"), list):
        folders = tuple(str(f) for f in data["managed_folders"])
        out["managed_folders"] = folders or None
    return out


def load() -> AppConfig:
    cfg = AppConfig()
    url, key = discover_from_xml()
    if url:
        cfg = replace(cfg, api_url=url)
    if key:
        cfg = replace(cfg, api_key=key)
    if env := _env_overrides():
        cfg = replace(cfg, **env)
    if toml := _toml_overrides(config_path()):
        cfg = replace(cfg, **toml)
    return cfg
