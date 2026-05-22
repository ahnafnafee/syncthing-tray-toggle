# Syncthing Tray Toggle

A tiny Windows system-tray app that flips a Syncthing folder between
**read-only** and **write + sync** with a single click, so you don't have to
dig through the Syncthing web GUI every time.

- **Read-only** = the folder is `receiveonly`: it receives updates from other
  devices, but your local edits are **not** pushed out (they're tracked
  locally).
- **Write + sync** = the folder is `sendreceive`: your local edits propagate to
  the cluster like a normal Syncthing folder.

Keep the folder read-only as your baseline; flip it to write+sync only when you
want your local changes to publish, then flip it back.

## How it works

The app talks to Syncthing's REST API and changes one field on the folder
config (`type`) via `PATCH /rest/config/folders/{id}`. It reads the API key and
address from Syncthing's own `config.xml` at runtime, so there's nothing to
configure and **no secret is stored in this project**.

It polls folder state every ~10 s, so the tray icon stays correct even if you
change a folder's type in the web GUI directly.

## Tray icon meanings

| Icon | Meaning |
|------|---------|
| 🔒 gray closed padlock | Folder is **read-only** (`receiveonly`) |
| 🔓 green open padlock | Folder is **write + sync** (`sendreceive`) |
| 🔴 red `?` disc | Syncthing is unreachable / API key rejected |
| small blue dot overlay | The folder is actively scanning/syncing |

- **Left-click** the icon: toggle the primary folder.
- **Right-click**: a menu with a per-folder toggle, *Force rescan*,
  *Revert local changes…* (only when read-only), *Open Syncthing GUI*,
  *Refresh now*, *Start on login*, and *Quit*.

## Requirements

- Windows, Syncthing running locally (v1.12+ for the PATCH endpoint; tested on
  v2.1).
- [uv](https://docs.astral.sh/uv/) for dependency management.

## Setup

```powershell
# from the project folder
uv sync
```

This creates a local `.venv` with the two dependencies (`pystray`, `Pillow`).

## Run

No console window (recommended):

```powershell
uv run pythonw syncthing_tray.pyw
```

Or run the venv interpreter directly (e.g. from a shortcut):

```
.venv\Scripts\pythonw.exe syncthing_tray.pyw
```

Use `python` instead of `pythonw` if you want a console for debugging.

## Start on login

Either click **Start on login** in the tray menu, or run:

```powershell
uv run python autostart.py --install     # create the Startup shortcut
uv run python autostart.py --uninstall   # remove it
uv run python autostart.py --status      # check
```

This drops a shortcut in your **Startup** folder pointing at the venv's
`pythonw.exe`, so the tray launches at login with no console window. It shows up
in Task Manager → Startup apps, so you can manage it there too.

## Configuration

None required. To override anything (remote instance, custom poll interval,
restrict to certain folders, or enable the optional read-only safeguards), copy
`config.example.toml` to `config.toml` and edit it. `config.toml` is gitignored.

The optional safeguards (both off by default):

- `reset_to_readonly_on_startup` — force folders back to read-only each launch.
- `auto_revert_after_minutes` — auto-return to read-only N minutes after you
  enable write (a timed type-flip; does **not** discard local changes).

## Notes & troubleshooting

- **Logs:** `%LOCALAPPDATA%\SyncthingTrayToggle\app.log`. If the app doesn't
  appear, a message box reports the error and the log has details.
- **"Force rescan" / large folders:** Syncthing's scan call blocks until the
  scan finishes, which can take a while for big folders. The app runs it in the
  background and never freezes. With the filesystem watcher on (the default),
  changes propagate automatically, so an explicit scan is rarely needed.
- **Revert local changes** is destructive — it discards local edits and
  restores the cluster's version. It's confirmation-gated and only available
  while the folder is read-only.
- **Security:** the API key is read from Syncthing's `config.xml` at runtime and
  never committed. You can rotate it anytime in Syncthing's settings.

## Optional: standalone .exe

You can later bundle a dependency-free executable with PyInstaller:

```powershell
uv run pyinstaller --noconsole --onefile --name SyncthingTrayToggle syncthing_tray.pyw
```

The autostart helper detects a frozen build and points the shortcut at the
`.exe` automatically.
