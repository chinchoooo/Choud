# Architecture

## Philosophy

> Build a system that is understandable from end to end.

This is a personal cloud, not AWS wearing a fake moustache. The most
important design goal is not maximum feature count — it's a codebase one
person can hold in their head.

Prefer: simple architecture, clear interfaces, strong correctness, good
tests, good documentation, measurable performance, incremental development.

Avoid: unnecessary microservices, Kubernetes, Elasticsearch, Kafka,
distributed databases, complicated cloud infrastructure, enterprise
multi-tenancy, unnecessary abstractions, rewriting mature cryptographic
primitives.

See [Explicit Non-Goals](#explicit-non-goals) for the full list of things
this project will not become.

## System overview

A hybrid control-plane / data-plane architecture:

```text
                         CLIENTS
                            |
              +-------------+-------------+
              |                           |
           Browser                   Desktop Client
              |                           |
              | HTTP                      |
              v                           v
        +---------------------------------------+
        |             Python API                |
        |               FastAPI                 |
        |                                       |
        | Authentication                        |
        | Authorization                         |
        | Metadata                              |
        | PostgreSQL                            |
        | File/folder API                       |
        +------------------+--------------------+
                           |
                    Local HTTP / IPC
                           |
                           v
        +---------------------------------------+
        |             C++ Engine                |
        |                                       |
        | Object Storage                        |
        | Hashing                               |
        | Deduplication                         |
        | Chunk processing                      |
        | Transfer primitives                   |
        | Synchronization                       |
        | Conflict detection                    |
        +------------------+--------------------+
                           |
                           v
                    Local Filesystem
```

**Python (control plane)** owns the HTTP API, authentication,
authorization, users, metadata (PostgreSQL), version metadata, sharing,
quotas, and API orchestration.

**C++ (data plane)** owns file bytes, hashing, object storage,
deduplication, chunk processing, resumable transfer primitives,
synchronization primitives, and filesystem operations.

Python and C++ communicate over a simple local HTTP API — no FFI in the
first version. The clean process boundary is intentional: it keeps each
side testable and replaceable on its own.

The final design principle:

```text
             "What does the user want?"
                       |
                       v
                    Python
                       |
                       v
             "Where are the bytes?"
                       |
                       v
                     C++
                       |
                       v
                     Disk
```

## Technology stack

**Backend:** Python 3.12+, FastAPI, SQLAlchemy, PostgreSQL, Alembic,
Pydantic, PyJWT, Argon2id.

**Native engine:** C++20, CMake, SQLite, Boost.Beast for HTTP, OpenSSL or
libsodium for cryptographic primitives (added when hashing lands in
Phase 4), GoogleTest. Modern C++: RAII, smart pointers, `std::filesystem`,
`std::optional`, exceptions only where appropriate. No unsafe C-style
memory management without a concrete reason.

**Frontend:** React, TypeScript, Vite, React Router, TanStack Query,
Tailwind CSS.

**Infrastructure:** Docker, Docker Compose, Caddy, Tailscale.

## Repository layout

```text
personal-cloud/
├── server/     Python control plane (FastAPI)
├── engine/     C++ data plane
├── client/     Desktop sync client (Phase 7+)
├── web/        React frontend
├── deployment/ Caddyfile, systemd units, deploy scripts
├── docs/       This documentation
└── scripts/    setup/backup/restore/healthcheck
```

Do not add additional layers unless they solve a real, current problem.

## Database Design

PostgreSQL stores metadata only. Actual file contents live on disk,
addressed by content hash (see [Content-Addressable Storage](#7-content-addressable-storage)).

```text
users            folders          files
-----            -------          -----
id               id               id
username         owner_id         owner_id
email            parent_id        folder_id
password_hash    name             name
is_active        created_at       mime_type
storage_quota    updated_at       size
created_at                        content_hash
updated_at                        storage_key
                                   current_version_id
                                   deleted_at
                                   created_at
                                   updated_at

file_versions    uploads          shares
-------------    -------          ------
id               id               id
file_id          owner_id         file_id
version_number   file_name        created_by
content_hash     file_size        token_hash
size             chunk_size       expires_at
created_at       total_chunks     download_limit
created_by       received_chunks  created_at
                 created_at
                 expires_at
                 status
```

`folders.parent_id` creates the folder hierarchy — cycles must be
prevented server-side. `files.deleted_at` implements trash (soft delete).
`file_versions` keeps old objects recoverable even after a file is
overwritten; don't garbage-collect an object while any version still
references it.

## 7. Content-Addressable Storage

Files are addressed by their SHA-256 content hash:

```text
SHA-256(file) = a94f2c8c...

stored at:
/data/cloud/objects/a9/a94f2c8c...
```

The first two hash characters become a directory prefix, so one directory
never accumulates an unbounded number of entries.

## 8. Deduplication

If two files hash to the same value, the physical bytes are stored once
and the database tracks references:

```text
A -> ABC123
B -> ABC123
```

Never physically delete an object while it is still referenced. Garbage
collection of unreferenced objects is a later refinement, not an MVP
requirement.

## 9. Hashing

SHA-256, computed by the C++ engine, must support **streaming** — never
load a multi-gigabyte file into memory just to hash it. Use a bounded
read buffer.

## 10. Chunked Uploads

Large uploads are split into chunks so one HTTP request is never
enormous:

```text
POST /api/uploads          -> upload_id
POST chunk 0, 1, 2, ...
POST /api/uploads/{id}/complete
```

The server tracks which chunks have been received, so a dropped
connection only requires re-uploading the missing chunk(s) — never the
whole file.

## 11. Chunk Storage

Temporary chunks live separately from final objects:

```text
/data/cloud/
├── objects/
└── uploads/
    └── <upload-id>/
        ├── 000000
        ├── 000001
        └── 000002
```

On completion: verify all chunks, reconstruct/stream the content,
compute and verify the SHA-256, store the final object, create metadata,
delete the temporary chunks. Interrupted uploads must be handled safely
— never left in a state that corrupts the object store.

## 12. Versioning

Every change to a file creates a new version. Old versions stay
recoverable (`GET /api/files/{id}/versions`,
`POST /api/files/{id}/versions/{version_id}/restore`). Never overwrite an
object still referenced by a version.

## 13. Trash

Deletion is soft: `deleted_at` is set, the file disappears from normal
listings, and it stays recoverable (`GET /api/trash`,
`POST /api/trash/{id}/restore`, `DELETE /api/trash/{id}`). Permanent
deletion only happens explicitly.

## 19. C++ Engine API

The C++ engine exposes only what the Python server actually needs — keep
the surface small (see [Rule 4](#implementation-rules)).

```text
GET  /health
POST /objects/exists
POST /objects/put
POST /objects/get
POST /objects/delete
POST /hash
POST /chunks/write
POST /chunks/finalize
```

The exact protocol may evolve as it's implemented. It is local-only: the
engine must never be reachable from outside the Docker-internal network
(see [Networking](#networking)).

## Storage Quota

Track `used_storage` against `users.storage_quota` and reject uploads
that would exceed it. Because of deduplication, distinguish **logical**
file size (what counts against a user's quota) from **physical** storage
used (shared across users who happen to store the same bytes) — see
[`storage.md`](storage.md#deduplication). Keep the initial implementation
simple; this is not the place for elaborate accounting.

## Authentication & Authorization

Passwords are hashed with Argon2id — never stored in plaintext. JWT
access tokens are short-lived; secrets live in environment variables, not
in git. Every resource operation verifies ownership server-side — a
frontend check is not security.

## Networking

The C++ engine listens only on `localhost` or the internal Docker
network; it is never published to the host or the internet. Remote
access goes through Tailscale, not router port forwarding. See
[`deployment.md`](deployment.md).

## Development Phases

Every phase must leave the project runnable. Definition of done for
Phase 1: `docker compose up` starts all services.

1. **Infrastructure** — repo, Docker Compose, FastAPI, PostgreSQL, React,
   C++ engine skeleton, CMake, health endpoints, config, test
   infrastructure. *(current phase — see the [README](../README.md#project-status))*
2. **Authentication** — users, registration, login, JWT, password
   hashing, authorization dependency.
3. **Basic Files** — folders, upload, download, rename, move, delete,
   metadata, web file manager.
4. **C++ Storage Engine** — SHA-256, object storage, content-addressable
   paths, deduplication.
5. **Chunked Uploads** — upload sessions, resumability, retries,
   finalization, cleanup of abandoned uploads.
6. **Versioning and Trash** — version history, restore, trash, permanent
   deletion, safe object cleanup.
7. **Desktop Sync** — filesystem watcher, local SQLite state, upload/download
   queues, reconciliation.
8. **Offline + Conflicts** — offline queue, reconnection, conflict
   detection, conflict copies.
9. **Remote Access** — deploy to real hardware: Ethernet, Docker, reverse
   proxy, Tailscale.
10. **Hardening** — rate limiting, security headers, logging, backup,
    restore, health monitoring, failure recovery.

## Implementation Rules

1. **Work incrementally.** One phase at a time. After each: build, run
   tests, fix failures, update docs, verify the system still runs.
2. **Do not over-engineer.** If a simple implementation works, use it. No
   dependency or abstraction without a concrete reason.
3. **Preserve separation of concerns.** Python: API, auth, metadata,
   business logic. C++: storage, hashing, chunks, filesystem, data-plane
   sync. React: UI. Desktop client: local filesystem sync.
4. **Keep the C++ API small.** Expose only what the storage layer
   actually needs.
5. **Never silently destroy data.** When uncertain, preserve the data,
   return an error, log the problem.
6. **Test failure cases.** Disk full, missing/corrupted object,
   interrupted upload, server disconnect, duplicate upload, invalid
   token, unauthorized access, conflicting modification.
7. **Never commit secrets.** `.env` is gitignored; `.env.example` is not.

## Explicit Non-Goals

Not implemented unless the core system is finished, and most never at
all: Kubernetes, microservices everywhere, distributed PostgreSQL, S3
compatibility, multi-region replication, CRDT-based synchronization,
end-to-end encrypted collaborative editing, an online Office/Docs clone,
video transcoding, enterprise RBAC, complex billing, multi-tenant SaaS, a
mobile app, AI features, blockchain, custom cryptography.

The project stays a personal cloud, not a startup incubator.

## See also

- [`storage.md`](storage.md) — object storage, dedup, chunking in detail
- [`synchronization.md`](synchronization.md) — desktop sync algorithm, conflicts
- [`api.md`](api.md) — HTTP API reference
- [`security.md`](security.md) — auth, authorization, hardening
- [`deployment.md`](deployment.md) — running this on real hardware
