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

**Currently implemented: Phase 1 — Infrastructure scaffold.**

- Repository layout matching `docs/architecture.md`'s design
- Docker Compose (PostgreSQL, backend, engine, frontend, reverse proxy)
- FastAPI skeleton with configuration and structured logging
- Local HTTP communication between the Python backend and the C++ engine
- Health endpoints on both services
- Test infrastructure (pytest, GoogleTest, Vitest)
- Every module for later phases exists as a stub file pointing at the
  phase that implements it — see `CLAUDE.md` for the roadmap.

Auth, files, storage, uploads, versioning, sync, and sharing are **not
yet implemented** — they land in later phases.

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
