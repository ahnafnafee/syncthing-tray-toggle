# Syncthing Tray Toggle — one-click read-only / send-receive switch for Windows

A lightweight **Windows system-tray app** that toggles a **Syncthing** folder
between **Receive Only (read-only)** and **Send & Receive (read-write sync)**
with a single click — no more digging through the Syncthing web GUI every time
you want to pause or resume pushing your local changes.

Keep a machine **read-only by default** so its local edits never sync out, then
flip a folder to **read-write** for a moment when you actually want to publish
changes — straight from the **tray icon**. Built in Python with
[`pystray`](https://github.com/moses-palmer/pystray) on top of the
[Syncthing REST API](https://docs.syncthing.net/dev/rest.html).

> **TL;DR:** left-click the tray padlock to toggle a Syncthing folder's
> `receiveonly` ⇄ `sendreceive` type. Gray = read-only, green = writable.

## Features

- 🔒 **One-click toggle** of a Syncthing folder's `type`
  (`receiveonly` ⇄ `sendreceive`) from the Windows system tray.
- 🎨 **At-a-glance status icon** — gray closed padlock (read-only), green open
  padlock (read-write), red `?` (Syncthing unreachable).
- 🔁 **Live polling** keeps the icon in sync if you change a folder type in the
  Syncthing web GUI directly.
- 🔑 **Zero-config & secret-safe** — reads the API key and URL from Syncthing's
  own `config.xml` at runtime; nothing sensitive is stored in this repo.
- 🚀 **Runs in the background** with no console window, and **starts on login**.
- 🧰 **No heavy dependencies** — just `pystray` + `Pillow`; HTTP via the Python
  standard library. Managed with [uv](https://docs.astral.sh/uv/).
- 🩹 **Self-healing launch** — double-clicking the script relaunches itself in
  the right virtual environment automatically.

## How it works

The app talks to Syncthing's local REST API and flips one field on the folder
config — `type` — via `PATCH /rest/config/folders/{id}`:

- **Read-only** = `receiveonly`: the folder receives updates from other devices,
  but your local edits are **not** pushed out (they're tracked locally).
- **Read-write** = `sendreceive`: your local edits propagate to the cluster like
  a normal Syncthing folder.

It reads the API key and address from Syncthing's own `config.xml`, so there's
nothing to configure and **no secret is stored in this project**. It polls every
~10 s so the tray icon stays correct even when you change a folder type
elsewhere.

## Tray icon meanings

| Icon | Meaning |
|------|---------|
| 🔒 gray closed padlock | Folder is **read-only** (`receiveonly`) |
| 🔓 green open padlock | Folder is **read-write / syncing** (`sendreceive`) |
| 🔴 red `?` disc | Syncthing is unreachable or the API key was rejected |
| small blue dot overlay | A folder is actively scanning / syncing |

- **Left-click** the icon: toggle the primary folder.
- **Right-click**: per-folder toggle, *Force rescan*, *Revert local changes…*
  (read-only folders only), *Open Syncthing GUI*, *Refresh now*,
  *Start on login*, and *Quit*.

## Requirements

- **Windows** 10/11.
- **Syncthing** running locally (v1.12+ for the PATCH endpoint; tested on v2.1).
- [**uv**](https://docs.astral.sh/uv/) for dependency management.

## Install

```powershell
# from the project folder
uv sync
```

This creates a local `.venv` with the two dependencies (`pystray`, `Pillow`).

## Run

**Run in the background (recommended)** — `pythonw.exe` is the windowless Python
interpreter, so there's no console window. `Start-Process` launches it detached
and returns your prompt immediately:

```powershell
Start-Process .\.venv\Scripts\pythonw.exe -ArgumentList syncthing_tray.pyw
```

Other ways to launch:

```powershell
# Foreground (ties up the terminal until you Quit; good for first-run testing)
uv run pythonw syncthing_tray.pyw

# With a console window, for debugging
uv run python syncthing_tray.pyw
```

**Double-click** also works: just double-click `syncthing_tray.pyw` (or a
launcher shortcut, below). Windows may run `.pyw` files with a different Python
that lacks the dependencies — the app detects this and **relaunches itself in
the project's `.venv` automatically**.

**Create double-click launcher shortcuts** (Desktop and/or project folder):

```powershell
uv run python autostart.py --desktop   # shortcut on your Desktop
uv run python autostart.py --here       # shortcut in the project folder
```

## Start on login

Click **Start on login** in the tray menu, or:

```powershell
uv run python autostart.py --install     # create the Startup shortcut
uv run python autostart.py --uninstall   # remove it
uv run python autostart.py --status      # check
```

This drops a shortcut in your **Startup** folder pointing at the venv's
`pythonw.exe`, so the tray launches at login with no console window. It also
appears in **Task Manager → Startup apps**.

> Run the `autostart.py` command with `python` (not `pythonw`) so its printed
> output is visible.

## Configuration

None required. To override anything (remote instance, custom poll interval,
restrict to certain folders, or the optional read-only safeguards), copy
`config.example.toml` to `config.toml` and edit it. `config.toml` is gitignored
because it may hold your API key.

Optional safeguards (both off by default):

- `reset_to_readonly_on_startup` — force folders back to read-only each launch.
- `auto_revert_after_minutes` — auto-return to read-only N minutes after you
  enable write (a timed type-flip; does **not** discard local changes).

## Troubleshooting

- **Logs:** `%LOCALAPPDATA%\SyncthingTrayToggle\app.log`. If the app doesn't
  appear, a message box reports the error and the log has details.
- **"No module named 'pystray'" on double-click:** your `.pyw` files are
  associated with a Python that lacks the deps (often Microsoft Store Python).
  The app auto-relaunches in the venv; if it can't, run `uv sync` first.
- **Two `pythonw.exe` in Task Manager = one app.** The venv's `pythonw.exe` is a
  launcher that spawns the real interpreter as a child; there's one tray icon.
  Quit from the tray menu rather than killing only the parent.
- **"Force rescan" on huge folders:** Syncthing's scan blocks until it finishes,
  so the app runs it in the background and never freezes. With the filesystem
  watcher on (the default), changes propagate automatically, so an explicit scan
  is rarely needed.
- **Revert local changes** is destructive — it discards local edits and restores
  the cluster's version. It's confirmation-gated and only offered while the
  folder is read-only.

## Security

The Syncthing API key is read from `config.xml` at runtime and never committed.
The local-only key can be rotated anytime in Syncthing's settings.

## Optional: standalone .exe

Bundle a dependency-free executable with PyInstaller:

```powershell
uv run pyinstaller --noconsole --onefile --name SyncthingTrayToggle syncthing_tray.pyw
```

The autostart helper detects a frozen build and points the shortcut at the
`.exe` automatically.

## License

[MIT](LICENSE) © Ahnaf An Nafee

## Tech / keywords

Syncthing · Windows system tray · tray icon toggle · receive-only ⇄ send-receive
· read-only sync · pause/resume Syncthing folder · Syncthing REST API ·
`X-API-Key` · Python · pystray · Pillow · uv · pythonw background app · run on
login / startup.
