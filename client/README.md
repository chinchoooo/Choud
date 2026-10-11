# Desktop sync client

`cloudsync` keeps a folder on your computer in sync with your Personal Cloud
server — in both directions, on Windows, macOS and Linux. It is a separate
program from the server: it talks to the server's HTTP API only (never the
storage engine) and owns just the local half of synchronization.

```text
 ~/CloudSync  ──scan──▶  reconcile  ◀──snapshot──  server API  (over Tailscale / LAN)
      ▲                      │
      └──── download ────────┴──── upload (conditional) / delete (to trash)
                         state database (.cloudsync/state.db)
```

## Install

Python 3.9 or newer.

```bash
cd client
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .                                       # installs the `cloudsync` command
```

## Use

```bash
# once: log in and choose the folder to keep in sync
cloudsync login --server http://100.64.0.5 --email you@example.com --folder ~/CloudSync

cloudsync sync      # one pass, then exit
cloudsync run       # keep syncing until you press Ctrl+C
cloudsync status    # what is tracked and what is waiting (and why)
cloudsync logout    # forget the saved login (files and history are kept)
```

`--server` is the address of the reverse proxy — with Tailscale, the server's
Tailscale IP or MagicDNS name (see [`../docs/deployment.md`](../docs/deployment.md)).
The password is asked for interactively (or taken from `CLOUDSYNC_PASSWORD`).
Settings and login tokens are saved per user (`%APPDATA%\CloudSync`,
`~/Library/Application Support/CloudSync` or `~/.config/cloudsync`) with
owner-only permissions.

Exit codes of `sync`: `0` ok · `1` some files had errors · `2` server
unreachable (changes are queued) · `3` login expired (run `login` again).

### Start on login

*Linux (systemd user service):*

```bash
mkdir -p ~/.config/systemd/user
cp packaging/cloudsync.service ~/.config/systemd/user/
systemctl --user enable --now cloudsync
```

*Windows:* create a Task Scheduler task "At log on" that runs
`<venv>\Scripts\cloudsync.exe run`. *macOS:* a launchd agent running
`cloudsync run`.

## How it decides what to do

Each cycle compares three views of every file:

| | |
| --- | --- |
| **local** | what is on disk now |
| **remote** | what the server has now (`GET /api/sync/snapshot`) |
| **base** | what both agreed on at the last sync (the state database) |

Comparing local and remote against the base tells "I edited it" apart from
"someone else edited it" from "we both did":

| local | remote | base | what happens |
| --- | --- | --- | --- |
| new | – | – | upload |
| – | new | – | download |
| changed | same as base | ✓ | upload as a **new version** |
| same as base | changed | ✓ | download |
| changed | changed | ✓ | **conflict**: keep both |
| same as base | deleted | ✓ | move local file to the local trash |
| deleted | same as base | ✓ | move it to the **server trash** |
| edited | deleted | ✓ | **the edit wins**: upload it again |
| deleted | edited | ✓ | **the edit wins**: download it back |
| same bytes | same bytes | – | nothing to transfer, just remember it |

The full table, with the reasoning, is in `cloudsync/reconciler.py`; it is a
pure function and every row is a unit test.

## What keeps your data safe

- **Conflicts keep both versions.** If a file changed on two devices, the
  server's version stays at the original name and yours is saved next to it as
  `report.conflict-2026-10-17.pdf`, then synced like any other file. Nothing is
  merged or overwritten.
- **Writes are conditional.** An upload says "apply this only if the file is
  still on the version I started from"; a delete says the same. If somebody
  changed it in between, the server refuses (`409`) and nothing is lost — the
  next cycle resolves it as a conflict.
- **Deletes are recoverable on both sides.** A file deleted elsewhere goes to
  `.cloudsync/trash/<time>/…` on your disk; a file you delete goes to the
  server's trash (and is still in its version history).
- **An edit always beats a delete**, in either direction.
- **Downloads are staged, hash-verified, then swapped in atomically**, so a
  crash or a dropped connection never leaves a half-written file.
- **Files still being written are skipped** (modified within the last 2 s, or
  changed while being read) rather than uploaded half-finished.
- **Server paths cannot escape the folder**: every local write goes through a
  check that rejects `..`, absolute paths and symlinks pointing outside.
- **Symlinks are never followed.**

## Offline and restarts

If the server is unreachable the client does not fail: local edits stay on disk
and are recorded as pending (`cloudsync status`). Every cycle is recomputed
from the disk and the state database, so there is no in-memory queue to lose:
quit, reboot, come back a week later, and the next sync uploads everything that
changed. Failing files back off (5 s, 10 s, … up to 5 min) without blocking the
others. Large uploads are chunked and **resume** with only the missing chunks,
even after a restart.

## What is not synced

- `.cloudsync/` (the client's own state), `.DS_Store`, `Thumbs.db`,
  `desktop.ini`, `~$*`, `.~lock.*`, `.#*`, `*.tmp`, `*.part`, `*.crdownload`,
  `*.swp`.
- Names this computer cannot hold (e.g. `report: final?.txt` on Windows) are
  skipped and listed in the output — they stay safely on the server.
- A file and a folder with the same path on the server (the server allows it, a
  disk does not) are skipped and reported.

## Known limits (deliberate, for now)

- **Folders are never deleted automatically**, only files. A folder you delete
  locally reappears; remove it on the server/web UI. (Rule 5: never silently
  destroy data.)
- **Renames and moves look like delete + create**, so a renamed large file is
  uploaded again (the server stores the bytes once, but they are still sent).
- Changes on the server are found by **polling** (default every 30 s), not push.
- Each cycle downloads the whole tree listing; fine for tens of thousands of
  files, not for millions.
- On case-insensitive filesystems (Windows, macOS), two server files that differ
  only by case cannot both exist locally.
- No bandwidth limit, selective sync or tray icon yet.

## Development

```bash
pip install -r requirements.txt      # also needs ../server/requirements.txt (see below)
pytest                               # 130+ tests, ~30 s
ruff check . && ruff format .
```

The integration tests import and run the **real server application** in process
(`../server`, over SQLite with the server's fake storage engine), so they need
the server's dependencies installed in the same environment
(`pip install -r ../server/requirements.txt`). They cover two devices, offline
mode, restarts, interrupted uploads, races and conflicts; `tests/conftest.py`
has a fault-injecting network wrapper for those.

Layout:

| Module | Job |
| --- | --- |
| `paths.py` | ignore rules, name legality, `safe_join` |
| `hasher.py` | streaming SHA-256 |
| `database.py` | SQLite state: base entries, queue, resumable uploads |
| `scanner.py` | what is on disk (re-hashes only changed files) |
| `api.py` | HTTP client: tokens, errors, uploads, downloads |
| `reconciler.py` | the three-way decision (pure) |
| `syncer.py` | one cycle: scan → snapshot → plan → execute |
| `uploader.py` / `downloader.py` | transfers, staging, local trash |
| `conflicts.py` | conflict copy names |
| `watcher.py` | filesystem events + debouncing |
| `main.py` | the `cloudsync` command |
