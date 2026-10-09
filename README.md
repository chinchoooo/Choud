# Personal Cloud

A self-hosted personal cloud storage and synchronization system, designed to
run on a repurposed Linux laptop. It provides the core experience of a
personal Google Drive/Dropbox: upload/download, folders, search, version
history, trash, deduplication, resumable uploads, desktop sync, offline
operation, conflict detection, and remote access.

This is a personal project, not an enterprise platform. See
[`docs/architecture.md`](docs/architecture.md) for the full design
philosophy and non-goals.

## Architecture

A hybrid control-plane / data-plane split:

```
Browser / Desktop Client
        | HTTP
        v
  Python API (FastAPI) ---- PostgreSQL (metadata)
        | local HTTP
        v
  C++ Engine (data plane) -- Local filesystem (bytes)
```

- **Python (`server/`)** owns the HTTP API, authentication, authorization,
  and metadata (PostgreSQL).
- **C++ (`engine/`)** owns object storage, hashing, deduplication, chunking,
  and synchronization primitives. It is never exposed to the internet —
  only the backend talks to it, over the internal Docker network.
- **React (`web/`)** owns the browser UI.
- **`client/`** will hold the desktop synchronization client (Phase 7).

See [`docs/architecture.md`](docs/architecture.md) for details.

## Project status

This repository is being built incrementally, phase by phase (see
[`docs/architecture.md`](docs/architecture.md#development-phases)).

**Currently implemented: Phase 6 — Versioning and Trash.**

- Repository layout
- Docker Compose (PostgreSQL, backend, engine, frontend, reverse proxy)
- FastAPI skeleton with configuration and structured logging
- Local HTTP communication between the Python backend and the C++ engine
- Health endpoints on both services
- Test infrastructure (pytest, GoogleTest, Vitest)
- User registration, login, JWT access/refresh tokens (Argon2id password
  hashing), and a `get_current_user` dependency every file endpoint uses
  (see `docs/api.md#auth`)
- Folders and files: create/rename/move/delete folders, upload/download/
  rename/move/delete files (delete moves a file to the trash),
  filename search — all owner-scoped, with path-traversal-safe storage
  (bytes are never written to a client-supplied path)
- A real C++ storage engine: streaming SHA-256 (OpenSSL), a
  content-addressed object store sharded by hash prefix, and
  deduplication — uploading the same bytes twice stores them once
  physically, verified by a test that inspects storage directly
- Resumable chunked uploads: large files are split into chunks client-side,
  uploaded independently, and reconstructed server-side with a streaming
  hash check — killing the connection partway and resuming only resends
  the chunks that never arrived (see `docs/api.md#uploads--resumable-chunked-uploads`
  and `docs/storage.md#chunked-uploads`)
- Versioning: uploading a file with the same name into the same folder adds
  a new version instead of a duplicate (identical bytes are a no-op).
  Every version is kept, can be downloaded, and can be restored — a restore
  adds a new version, so history is never rewritten
  (see `docs/api.md#versions`)
- Trash: deleted files can be listed, restored (to the original folder, or
  the root if it is gone; renamed `name (restored).ext` on a clash), or
  permanently deleted — which frees a stored object only when no other file
  or version, of any user, still uses it (see `docs/api.md#trash`)
- A working web UI: register/login, a file browser (breadcrumb
  navigation, upload — chunked with a "Resume upload" button for large
  files — new folder, rename, move, delete, download, search), a per-file
  version list with download/restore, and a Trash page

Desktop and phone sync, sharing, 2FA and search-by-content are **not yet
implemented** — see the roadmap in `CLAUDE.md` for the order they land in.

## Getting started

```bash
cp .env.example .env
# edit .env if you want non-default credentials

make docker-up
```

This starts PostgreSQL, the C++ engine, the FastAPI backend, the React
frontend, and a Caddy reverse proxy.

Check that everything is healthy:

```bash
curl http://localhost:8000/api/health
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
make migrate         # run Alembic database migrations
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — system design, philosophy, phases
- [`docs/storage.md`](docs/storage.md) — content-addressable storage, dedup, chunking
- [`docs/synchronization.md`](docs/synchronization.md) — desktop sync algorithm, conflicts
- [`docs/api.md`](docs/api.md) — HTTP API reference
- [`docs/security.md`](docs/security.md) — auth, authorization, and hardening notes
- [`docs/deployment.md`](docs/deployment.md) — running this on real hardware

## License

[MIT](LICENSE)
