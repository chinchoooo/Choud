# Choud

<div align="center">
  <img src="choud-brand-assets/choud-logo-light.svg" alt="Choud" width="400" />
</div>

**Your own cloud. Your own server. Nobody else's.**

Choud is a self-hosted Google Drive alternative that runs on one spare Linux machine at home.
Your files live on your disk, are stored once however many times they are uploaded, and are reachable
from your phone and laptops over Tailscale or your home network. There are no subscriptions, no
tracking and no storage limit beyond the drive you give it.

## What you get

| | |
| --- | --- |
| **Files** | Folders, drag-and-drop and resumable uploads (a dropped connection only resends what is missing), duplicate-free storage, a photo timeline, favorites, recents, an activity log |
| **Never lose anything** | Every overwrite is a new version you can restore, deleted files wait in a trash, nothing is destroyed on a doubt |
| **Find anything** | Search by file name and by what is written *inside* documents (text, code, PDF, Word, OpenDocument) |
| **View anywhere** | Built-in viewers for images, video, audio, PDF and text, with thumbnails; no other app needed |
| **Share** | Public links with an expiry and a password, either view-only or "add and edit" (deletes go to your trash, replaced files keep their old version); no accounts needed for the people you share with. One command (`scripts/enable-public-links.sh`) makes links work from anywhere without exposing the rest of your drive, with an instant pause switch |
| **Phone** | An Android app backs up photos and videos in the background with the phone's real dates and resumes if the connection drops. Its Photos tab is built for slow links: the whole library lives on the phone, blurry placeholders paint instantly, thumbnails arrive a screenful at a time. It also searches, uploads, shares, and manages trash and links (see [`docs/mobile-perf.md`](docs/mobile-perf.md)) |
| **Laptops** | A desktop client either mirrors a folder both ways (with conflict copies, never silent overwrites) or quietly backs up chosen folders whenever the laptop can reach your server |
| **Time travel** | Rewind: see any folder as it was at an earlier moment and put it back, one file or the whole drive, with a preview first (an undo for ransomware and bad syncs) |
| **Vault** | An encrypted vault whose files are sealed in your browser: the server never sees the contents or even the file names |
| **Requests** | File-request links (people can send you files but see nothing), one-time links, and a storage report with duplicate and old-version clean-up |
| **People** | Invite family and friends with one-time codes; each gets their own storage and quota |
| **Safe by default** | Optional two-factor login, a registration lock, rate limiting, hash-checked uploads, scripts that can be audited, nightly verified backups and webhook alerts |

The look is deliberately retro: black and white, monospace, square corners, with modern line icons.

## How it is built

A control-plane / data-plane split, each part doing what it is best at:

```
Browser · Android app · Desktop client
                 | HTTP (Tailscale or LAN)
                 v
      Python API (FastAPI) ---- PostgreSQL (metadata, search index)
                 | internal network only
                 v
      C++ engine (data plane) -- your disk (bytes, by hash)
```

- **Python (`server/`)** owns the API, accounts, permissions, versions, sharing and search.
- **C++ (`engine/`)** owns hashing, content-addressed storage, deduplication and chunk assembly. It
  is never exposed to the network: only the backend talks to it.
- **React (`web/`)** is the browser app. **Kotlin (`android/`)** is the phone app.
  **Python (`client/`)** is the desktop client.

See [`docs/architecture.md`](docs/architecture.md) for the reasoning and the non-goals.

## Project status

Everything above is built and tested (server, engine, web, Android and desktop client each have their
own suite). It runs on the author's own laptop server. Honest gaps: the Android app has had little
time on a real phone, per-user sharing (sharing with named accounts) is deliberately not built (links
are the only way to share), passkeys and comments are not built, and there is no iOS app. The detailed
roadmap and handoff notes are in the phase documents under [`docs/`](docs/).

## Getting started

**Run it for real** (a Linux machine with Docker; full guide in
[`docs/deployment.md`](docs/deployment.md)):

```bash
scripts/setup.sh      # creates .env with strong random secrets
scripts/deploy.sh     # checks the machine, builds, starts, waits until healthy
```

**Develop on it** (hot reload, placeholder secrets, nothing to configure):

```bash
make dev              # then open http://localhost:8080
```

Either way this starts PostgreSQL, the C++ engine, the FastAPI backend, the
web app and a Caddy reverse proxy. Database migrations run automatically when
the backend starts. In the real stack only the proxy publishes a port.

Check that everything is healthy:

```bash
scripts/healthcheck.sh        # or: curl http://localhost/api/health
```

```json
{
  "status": "healthy",
  "database": "healthy",
  "engine": "healthy",
  "storage": "healthy"
}
```

Stop everything:

```bash
make docker-down
```

## Development

See the [`Makefile`](Makefile) for the full list of commands:

```bash
make install       # install Python + Node dependencies locally
make test           # run backend + engine tests
make lint            # lint backend + frontend
make format          # format backend + frontend
make engine-build    # build the C++ engine with CMake
make engine-test     # build and run engine tests via ctest
make migrate         # run Alembic migrations by hand (the backend also does this on start)
```

## Documentation

- [`docs/guide.md`](docs/guide.md) — **start here**: the complete guide to the whole system, with a learning path
- [`docs/ai-prompt.md`](docs/ai-prompt.md) — ready-made prompts to learn it with an AI, or to keep building it safely
- [`docs/architecture.md`](docs/architecture.md) — system design, philosophy, phases
- [`docs/storage.md`](docs/storage.md) — content-addressable storage, dedup, chunking
- [`docs/synchronization.md`](docs/synchronization.md) — desktop sync algorithm, conflicts
- [`docs/api.md`](docs/api.md) — HTTP API reference
- [`docs/security.md`](docs/security.md) — auth, authorization, and hardening notes
- [`docs/deployment.md`](docs/deployment.md) — running this on real hardware (laptop server + Tailscale)
- [`docs/errors.md`](docs/errors.md) — real problems hit during setup, and their fixes

## License

[MIT](LICENSE)
