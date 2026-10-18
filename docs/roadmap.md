# Roadmap and handoff notes

This is the working record of how Choud was built, phase by phase: what each phase decided, what
shipped, what is still missing, and the traps found along the way. It is meant for contributors (human
or AI) who want to continue the work. Start with [`guide.md`](guide.md) for the system as it is today and
[`architecture.md`](architecture.md) for the rules; come here when you need the *why* behind a decision
(the code comments refer to the "Phase N decisions" below) or the list of what to build next.

Contents: orientation and the non-negotiable rules (section 0), the current state (1), the per-phase
notes (2 to 10, 16 and 18), the definition of done (11) and the extended roadmap (12).

---

## 0. Orientation

- [`docs/architecture.md`](architecture.md) — philosophy, system
  design, tech stack, database schema, phase list, implementation rules,
  explicit non-goals. **The rules in here are not suggestions.**
- [`docs/storage.md`](storage.md) — object storage, dedup, chunking design.
- [`docs/synchronization.md`](synchronization.md) — desktop sync algorithm, conflicts.
- [`docs/api.md`](api.md) — HTTP API reference (implemented + planned).
- [`docs/security.md`](security.md) — auth, authorization, filesystem safety rules.
- [`docs/deployment.md`](deployment.md) — running this on real hardware.
- [`docs/errors.md`](errors.md) — real problems hit during first
  deployment to a real server, and their actual fixes. Read this before
  debugging a fresh `docker compose up` failure from scratch.
- [`README.md`](../README.md) — quickstart and current project status.

### Non-negotiable rules (see `docs/architecture.md#implementation-rules`)

1. Work one phase at a time. After each phase: build, run tests, fix
   failures, update docs, verify `docker compose up` still works end to end.
2. Don't over-engineer. No dependency or abstraction without a concrete
   reason. No Kubernetes, no microservices, no distributed anything — see
   `docs/architecture.md#explicit-non-goals`.
3. Keep the separation of concerns: Python owns API/auth/metadata/business
   logic, C++ owns storage/hashing/chunks/filesystem/data-plane sync,
   React owns UI, the desktop client owns local filesystem sync.
4. Keep the C++ HTTP API small — only what the Python backend actually calls.
5. Never silently destroy data. On uncertainty: preserve the data, return
   an error, log the problem.
6. Test failure cases, not just the happy path (disk full, missing/corrupt
   object, interrupted upload, server disconnect, duplicate upload, invalid
   token, unauthorized access, conflicting modification).
7. Never commit secrets. `.env` is gitignored; only `.env.example` is tracked.

### How to verify the stack at any point

```bash
cd server && pip install -r requirements.txt && pytest
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build --parallel && ctest --test-dir engine/build --output-on-failure
cd web && npm install && npm run build && npm run lint && npm run test
docker compose config   # validates docker-compose.yml without building
docker compose up -d --build && curl -f http://localhost:8000/api/health
```

(`make test`, `make engine-test`, `make lint` wrap most of this — see
[`Makefile`](../Makefile).)

---

## 1. Current state (version 0.5.1)

Milestone 1 ("daily driver") and most of Milestone 2 are built and released; see
[`../CHANGELOG.md`](../CHANGELOG.md) for what each version added. In short:

- **Server, engine, web, desktop client:** everything in sections 2 to 12 below, plus search inside files,
  two-factor login, invites and a registration lock, edit links and file requests, Rewind, the encrypted
  Vault, a storage report, photo library views, thumbnails and viewers, public share links with a pause
  switch (`scripts/enable-public-links.sh`), and the fast-photos work (ThumbHash placeholders, WebP
  thumbnails, a batch thumbnail endpoint, a library index with delta sync; see
  [`mobile-perf.md`](mobile-perf.md)).
- **Android app** (`android/`): background camera-roll backup, resumable uploads, a Photos tab backed by a
  local database and merged with photos not yet backed up, Files, search, upload and share-into-Choud,
  trash, shared links, storage and sign-in history screens, and built-in viewers. It builds its views in
  code with its own component kit; it has been verified on an emulator, with little time on real phones.
- **Not built:** sharing with named accounts (links are the only way to share, on purpose), passkeys,
  comments, two-way folder sync on the phone, an iOS app, a tablet layout, a fast-scroll date handle, and
  an independent security audit.

The rest of this section is the snapshot taken at the end of Phase 8, kept because its handoff notes are
still useful. Counts and "not yet" statements in it are out of date.

### Earlier snapshot (end of Phase 8)

Auth, folders/files, content-addressed storage with deduplication,
resumable chunked uploads, file versioning and a restorable trash are all
implemented and wired together end-to-end, and since then the **desktop sync
client with offline mode and conflict copies** (`client/`, Phases 7–8), the
**production deployment stack and operator scripts** (Phase 9, verified in an
isolated Compose project; the real-laptop step is pending), and the
**10-lite hardening** (rate limiting, scheduled backups/health, housekeeping)
are built. Still nothing below:

- No sharing, no 2FA, no content search, no thumbnails (Milestone 2).
- **No phone sync app** (Phases 16 + 18a — the last Milestone 1 item; needs a
  decision on the phone platform, see `docs/mobile.md`).
- No general garbage collection of orphaned storage objects (deliberately
  deferred to Phase 15 — see `docs/storage.md#deduplication`). Only a
  trash purge deletes objects, and only unreferenced ones.
- Not yet run on the real target laptop (see Phase 9's status below).

**Milestone 1 status ("daily driver"):** 6 ✅ · 9 prepared (run
`scripts/deploy.sh` on the laptop) · 10-lite ✅ · 7 ✅ · 8 ✅ · 16/18a ⏳.

What **does** exist and work today (verified — `pytest` (114 tests, on
both SQLite and real PostgreSQL 16), `ctest` (47 tests, not re-run in
Phase 6 — no engine changes), `ruff check`, frontend `tsc`/`eslint`/`vitest`
(28 tests) and `vite build` all pass; `docker compose up -d --build` has now actually been run
end-to-end on a real server, including a real upload verified against
the database, the physical object store, and a re-computed hash — see
[`docs/errors.md`](errors.md) for the real deployment bugs that
were found and fixed along the way):

- `docker-compose.yml`: postgres, engine (internal-only), backend,
  frontend, Caddy reverse proxy.
- `server/`: FastAPI app (`app/main.py`), config (`app/core/config.py`,
  reads `.env`), SQLAlchemy engine + `Base` (`app/core/database.py`),
  structured logging (`app/core/logging.py`), `GET /api/health`
  (`app/api/health.py`) checking DB/engine/storage.
- **Auth (Phase 2):** `User` model (`app/models/user.py`, UUID primary
  key via the cross-dialect `app/core/types.GUID`), Argon2id hashing +
  JWT issuance/verification (`app/core/security.py`), `get_current_user`
  dependency (`app/core/dependencies.py`), `POST /api/auth/register`,
  `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout`,
  `GET /api/auth/me`. Logout is intentionally stateless — no session/
  blocklist table (Rule 2).
- **Folders & files (Phase 3):** `Folder`/`File` models, `file_service.py`
  (cycle-safe folder move/rename, path-traversal-safe filenames, soft
  file delete / hard empty-folder delete), `GET/POST/PATCH/DELETE
  /api/files/*` and `/api/folders/*`, `GET /api/search`. `GET /api/files`
  doubles as a directory listing (`{folder, subfolders, files}`) — see
  `docs/api.md`.
- **Storage engine (Phase 4):** `engine/` now has a real streaming
  SHA-256 hasher (`hashing/hasher.cpp`, OpenSSL EVP), a content-addressed
  `ObjectStore` with two-char shard directories and dedup
  (`storage/object_store.cpp`), and a `StorageManager` facade the HTTP
  layer calls. `engine_server.cpp` implements `POST /hash`,
  `/objects/exists`, `/objects/put`, `/objects/get`, `/objects/delete`
  over small hand-rolled JSON envelopes (see `docs/storage.md`). On the
  Python side, `storage_service.py` wraps an extended `engine_client.py`;
  `file_service.upload_file`/`prepare_download` stage bytes on the shared
  `STORAGE_ROOT` volume and hand off to the engine — `File.content_hash`
  is now always populated, and two uploads with identical bytes share one
  physical object (verified by a test that inspects the fake engine's
  object directory directly).
- `web/`: Vite + React + TS + React Router + TanStack Query + Tailwind.
  `AuthContext` + `ProtectedRoute` + `Login`/`Register` pages (added
  alongside Phase 3, since the file UI needs auth to function even though
  Phase 2's own plan didn't call for a web login screen), plus `Files.tsx`
  — breadcrumb navigation, upload (chunked + resumable for large files as
  of Phase 5), new folder, rename/move (via `window.prompt`, deliberately
  minimal), delete, download, search.
- **Chunked uploads (Phase 5):** `engine/` gained `chunks::ChunkStore`
  (temp chunk storage, `uploads/<id>/NNNNNN`) and `chunks::ChunkManager`
  (verify/reconstruct/finalize into the object store, or abandon), plus
  `POST /chunks/write`, `/chunks/finalize`, `/chunks/abandon` on
  `engine_server.cpp`. `server/app/models/upload.py` tracks sessions;
  `app/services/upload_service.py` + `app/api/uploads.py` expose
  `POST /api/uploads`, `GET /api/uploads/{id}`,
  `POST /api/uploads/{id}/chunks/{index}`,
  `POST /api/uploads/{id}/complete`, `DELETE /api/uploads/{id}`.
  `web/src/api/uploads.ts` chunks large files client-side and can resume
  a failed upload by only resending what the server says is missing.
- **Versioning and trash (Phase 6):** `FileVersion` model + migration
  `0004` (backfills version 1 for existing files),
  `app/services/version_service.py` (`save_content` — new file, new
  version, or no-op for identical bytes; list/get/restore),
  `app/services/trash_service.py` (list, restore with clash handling,
  purge with reference-checked object deletion), routers
  `app/api/versions.py` and `app/api/trash.py`. Both upload paths
  (`file_service.upload_file`, `upload_service.complete_upload`) go
  through `version_service.save_content`. Web: `pages/Trash.tsx` and
  `components/VersionHistory.tsx` in the plain prompt/confirm style.
- Every module for phases 7+ still exists as a **stub file with a
  one-line comment** pointing at the phase that fills it in. Start there
  — the file layout already matches `docs/architecture.md`'s repo
  structure, you're filling in blanks, not designing from scratch.

**Notes for whoever picks up the next phase** (each phase's detailed
handoff notes are under its own section below):

- The Python test suite runs against an in-memory SQLite database
  (`server/tests/conftest.py`), not real PostgreSQL, via the cross-dialect
  `app/core/types.GUID` — keep using `GUID()` for new primary/foreign key
  columns. It also runs against `FakeEngineClient`
  (`server/tests/fake_engine.py`), not a real running C++ engine process —
  keep new engine-backed calls going through `storage_service`, not
  `engine_client` directly, so the fake keeps intercepting them.
- The C++ test suite (`engine/tests/`) now needs `libssl-dev`,
  `libboost-dev`, and `libgtest-dev`/`googletest` — all three were
  installed via `apt-get` in this sandbox to build and run `ctest`;
  they're already in `engine/Dockerfile`'s build stage (plus `libssl3` in
  the runtime stage), but a fresh dev machine running `make engine-build`
  directly (outside Docker) will need them installed too.

---

## 2. Phase 2 — Authentication ✅ done

**Goal:** register/login/JWT, all later endpoints protected.

- `server/app/models/user.py`: SQLAlchemy `User` model per
  `docs/architecture.md#database-design` (id, username, email,
  password_hash, is_active, storage_quota, created_at, updated_at).
- `server/app/core/security.py`: Argon2id hashing (`argon2-cffi`, already
  in `requirements.txt`) — `hash_password` / `verify_password`; JWT
  issuance/verification with `PyJWT` using `settings.jwt_secret`,
  `settings.jwt_algorithm`, `settings.access_token_expire_minutes`.
- `server/app/core/dependencies.py`: `get_current_user` FastAPI
  dependency — decodes the bearer token, loads the user via `get_db`,
  raises 401 on failure. Every later endpoint depends on this.
- `server/app/schemas/auth.py`: Pydantic request/response models
  (RegisterRequest, LoginRequest, TokenResponse, UserResponse — never
  echo `password_hash`).
- `server/app/api/auth.py`: wire up
  `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/refresh`,
  `POST /api/auth/logout`, `GET /api/auth/me` (see `docs/api.md`).
- Register the router in `server/app/main.py`
  (`app.include_router(auth.router)`).
- Generate the first Alembic migration:
  `cd server && alembic revision --autogenerate -m "add users table"` then
  `alembic upgrade head`. Uncomment the model import in
  `server/migrations/env.py`.
- `server/tests/test_auth.py`: registration, duplicate email/username,
  login success/failure, token expiry/refresh, `get_current_user` rejects
  bad/missing/expired tokens, password is never returned or logged.

**Done when:** a fresh user can register, log in, get a JWT, and hit a
dependency-protected endpoint; a bad token is rejected; `pytest` passes.

**Status:** done. The migration (`0001_add_users_table.py`) was
hand-written rather than via `alembic revision --autogenerate`, since no
live PostgreSQL server is reachable in a dev/CI sandbox — verify it
against a real Postgres with `make migrate` the first time you have one
running. `POST /api/auth/logout` returns `204` and requires a valid
access token but performs no server-side revocation — see the note on
Phase 1's "Current state" above for why.

---

## 3. Phase 3 — Basic Files ✅ done

**Goal:** a working private cloud — no content-addressing yet (that's
Phase 4). Store bytes directly under `STORAGE_ROOT`, keyed by a
server-generated file ID; swap in the C++ engine in Phase 4 without
changing the API surface.

- `server/app/models/folder.py`, `server/app/models/file.py`: per
  `docs/architecture.md#database-design`. Prevent folder cycles at the
  service layer (a folder can't become its own descendant's parent).
- `server/app/schemas/files.py`, `server/app/schemas/folders.py`.
- `server/app/services/file_service.py`: upload (validate filename,
  reject path traversal — see `docs/security.md#filesystem-safety` — never
  build a path from a client-supplied filename), download, rename, move,
  delete (soft — sets `deleted_at`), metadata.
- `server/app/api/files.py`:
  `GET /api/files`, `POST /api/files/upload`, `GET /api/files/{id}`,
  `GET /api/files/{id}/download`, `PATCH /api/files/{id}`,
  `DELETE /api/files/{id}`.
- `server/app/api/folders.py`:
  `POST /api/folders`, `GET /api/folders/{id}`, `PATCH /api/folders/{id}`,
  `DELETE /api/folders/{id}`.
- `server/app/api/search.py`: `GET /api/search?q=...` — PostgreSQL
  `ILIKE`/full-text search over filename, mime type, folder, dates. No
  Elasticsearch.
- Every route requires `get_current_user` and filters by `owner_id` —
  never trust a client-supplied owner/user ID.
- Web (`web/src/`): add `pages/Files.tsx` (folder navigation, upload, new
  folder, rename, move, delete, download — see the mockup in
  `docs/architecture.md`'s original spec or just build a clean table view),
  TanStack Query hooks in `web/src/api/files.ts` / `folders.ts`, routes in
  `web/src/App.tsx`. Reuse the `apiGet` pattern in `web/src/api/client.ts`;
  add `apiPost`/`apiPatch`/`apiDelete` alongside it as needed.
- `server/tests/test_files.py`, `server/tests/test_folders.py`: upload,
  download round-trip, rename, move, delete/trash, path traversal
  rejected, folder cycle rejected, cross-user access denied (401/403/404,
  never leaking another user's data).

**Done when:** you can log in through the web UI, create folders, upload
a file, download it back byte-identical, rename/move/delete it, and search
finds it.

**Status:** done — backend and web UI both verified. Design notes for
whoever picks up Phase 4:

- **Storage layout:** bytes live at `${STORAGE_ROOT}/raw/<file.id.hex>`
  (see `file_service._raw_path`). Phase 4 replaces these direct
  `Path.write_bytes`/`FileResponse(path=...)` calls with calls through
  `storage_service` → the C++ engine's content-addressable store, and
  starts populating `File.content_hash`. The `raw/` layout is
  deliberately distinct from the engine's future `objects/` layout so the
  swap is unambiguous — don't repurpose `raw/`.
- **`GET /api/files`** does double duty as a directory listing: pass
  `folder_id` (or omit it for root) and get back
  `{folder, subfolders, files}` in one call — there's no separate
  `GET /api/folders` list endpoint, since the exact endpoint list in
  `docs/api.md` doesn't include one. `GET /api/folders/{id}` stays a
  single folder's metadata only (for breadcrumbs / rename dialogs).
- **Folder delete is hard delete**, and only succeeds on an empty folder
  (409 otherwise) — folders have no `deleted_at` in the schema, and
  cascading a delete would violate Rule 5. File delete is soft
  (`deleted_at`), per the CLAUDE.md spec above.
- **Folder name uniqueness** is enforced at the service layer (per
  `owner_id` + `parent_id`), not with a DB constraint — a `NULL`
  `parent_id` in a unique index behaves inconsistently across dialects,
  and the app-level check is simpler and portable. Don't add a DB unique
  constraint on `(owner_id, parent_id, name)` without checking this.
- **Web auth:** `web/src/auth/AuthContext.tsx` + `ProtectedRoute.tsx` +
  `pages/Login.tsx`/`Register.tsx` were added — the CLAUDE.md Phase 2 plan
  didn't call for a web login screen, but Phase 3's file UI can't function
  without one (every file/folder endpoint requires a bearer token), so it
  landed here instead. Tokens live in `localStorage`
  (`web/src/api/client.ts`); a 401 triggers one silent refresh-and-retry
  before giving up.
- **Move/rename UI** uses `window.prompt`/`window.confirm` rather than a
  folder-picker modal or drag-and-drop — deliberately minimal (Rule 2).
  Each folder row shows the first 8 chars of its id so you have something
  to paste into the "destination folder ID" prompt. Revisit this if it's
  too clunky in practice; it's the first thing worth polishing later, not
  a hard requirement.
- **Test DB:** `server/tests/conftest.py` now also auto-uses a temp dir
  for `file_service.settings.storage_root` (see `_isolated_storage_root`)
  so upload tests don't write to `/data/cloud`. Follow the same pattern
  for any new tests that touch disk.

---

## 4. Phase 4 — C++ Storage Engine ✅ done

**Goal:** move actual bytes into the C++ engine, content-addressed, with
deduplication. The Python `file_service` from Phase 3 switches from
direct filesystem writes to calling the engine.

- `engine/include/hashing/hasher.hpp` + `engine/src/hashing/hasher.cpp`:
  streaming SHA-256. Use OpenSSL's EVP API (add
  `find_package(OpenSSL REQUIRED)` and link `OpenSSL::Crypto` in
  `engine/CMakeLists.txt` — it was deliberately left out of Phase 1 since
  nothing used it yet). Never reinvent the hash algorithm itself (Rule:
  don't rewrite mature crypto primitives). Read in bounded chunks (e.g.
  64KB), never load a whole file into memory.
- `engine/include/storage/object_metadata.hpp`,
  `engine/include/storage/object_store.hpp` +
  `engine/src/storage/object_store.cpp`: content-addressable storage per
  `docs/storage.md#the-objectstore-interface` and
  `docs/architecture.md#7-content-addressable-storage` (two-char hash
  prefix directory sharding under `${STORAGE_ROOT}/objects/`).
- `engine/include/storage/storage_manager.hpp` +
  `.cpp`: reference counting for dedup (an object is deletable only when
  nothing references it — don't implement GC yet, just don't break it).
- Extend `engine/src/api/engine_server.cpp`'s router with:
  `POST /objects/exists`, `POST /objects/put`, `POST /objects/get`,
  `POST /objects/delete`, `POST /hash` (see `docs/api.md`'s internal API
  table). Keep request/response bodies small JSON envelopes; the engine
  still only listens on the Docker-internal network — never add auth
  logic here, that's the backend's job (`docs/security.md#the-engine-boundary`).
- `server/app/services/storage_service.py`: thin wrapper calling
  `EngineClient` (extend `server/app/services/engine_client.py` with
  `exists`/`put`/`get`/`delete`/`hash` methods, following the existing
  `check_health` pattern).
- Update `server/app/services/file_service.py` to hash uploads, call
  `storage_service` instead of writing directly to disk, and store
  `content_hash` on the `File`/`FileVersion` rows. Two uploads with
  identical bytes must now share one object on disk — write a test for it.
- `engine/tests/hashing_tests.cpp`, `engine/tests/storage_tests.cpp`:
  replace the stub comments with real GoogleTest cases — known SHA-256
  vectors, put/get/exists/remove round-trip, missing-object and
  corrupted-object handling, dedup reference counting. Add them to
  `engine/tests/CMakeLists.txt`'s `engine_tests` sources (or a new test
  binary if you prefer one per module — either is fine, `ctest` just needs
  to find them).
- `server/tests/test_files.py`: add a "duplicate upload doesn't duplicate
  storage" test (Definition of Done step 9-10 in `docs/architecture.md`
  or the original task spec — hash the object on disk directly, or check
  physical storage size doesn't grow).

**Done when:** uploading the same file content twice stores it once
physically; a corrupted or missing object returns a clean error, not a
crash; `ctest` and `pytest` both pass.

**Status:** done — 25/25 `ctest` cases and 63/63 `pytest` cases pass, both
lint clean. Notes for whoever picks up Phase 5:

- **JSON in the engine:** `engine_server.cpp` parses/writes its tiny
  request/response bodies with a hand-rolled regex extractor
  (`json_string`/`json_escape` in an anonymous namespace), not a JSON
  library — the payloads are simple flat objects exchanged only between
  our own trusted, Docker-internal processes (Rule 2: no dependency
  without a concrete reason). If Phase 5's chunk endpoints need anything
  more structured than flat string/number fields, reconsider this and
  pull in a real JSON library rather than growing the regex hack.
- **Reference counting lives in Postgres, not C++** —
  `StorageManager::remove_object` is unconditional; nothing calls it yet.
  See the note added to `docs/storage.md#deduplication`.
- **Shared-volume path passing:** engine HTTP calls pass paths (not
  bytes) because `backend` and `engine` mount the same `storage_data`
  volume (`docker-compose.yml`). If that ever stops being true (e.g. the
  engine moves to a different host), this whole request shape needs to
  change to actually stream bytes over HTTP instead.
- **`put()` and `get()` semantics:** `put` *consumes* its source path
  (moves it into the store); `get` *copies* out (the stored object must
  survive the read). Get both directions right in Phase 5's chunk
  finalize path — a chunk being reconstructed into a final object is a
  `put`-shaped operation.
- **Test isolation:** `server/tests/fake_engine.py`'s `FakeEngineClient`
  stands in for the real engine in Python tests (mirrors `ObjectStore`'s
  sharding/dedup/corruption-detection behavior with plain `hashlib` +
  filesystem calls) so `pytest` never needs a running engine process. Any
  new engine-backed Python service call should go through
  `storage_service`, not `engine_client` directly, so this fake keeps
  working.
- **Not verified:** the actual `docker build` of `engine/Dockerfile` and
  `docker compose up` end-to-end — this sandbox has no Docker daemon, only
  `docker compose config` (which validates the YAML). The Dockerfile now
  installs `libssl-dev`/`libssl3` alongside the existing `libboost-dev`;
  double-check that build the first time you have a working daemon.

---

## 5. Phase 5 — Chunked Uploads

**Goal:** resumable uploads — a dropped connection only requires
re-sending the missing chunk(s).

- `server/app/models/upload.py`: `Upload` model per
  `docs/architecture.md#database-design`. New Alembic migration.
- `server/app/schemas/uploads.py`: create-session request/response,
  chunk-ack response, complete request/response.
- Add upload-session endpoints (there's no `server/app/api/uploads.py` in
  the initial skeleton — add one and register it in `server/app/main.py`,
  it's the natural place): `POST /api/uploads` (create a session, return
  `upload_id` + expected chunk layout), a chunk-upload endpoint (e.g.
  `POST /api/uploads/{id}/chunks/{index}`), and
  `POST /api/uploads/{id}/complete` (see `docs/api.md`). Validate upload
  ownership and chunk metadata on every call (Rule: never trust client
  input — `docs/security.md`).
- `engine/include/chunks/chunk_store.hpp`, `chunk_manager.hpp` + their
  `.cpp` files under `engine/src/chunks/`: temporary chunk storage under
  `${STORAGE_ROOT}/uploads/<upload-id>/NNNNNN` per
  `docs/architecture.md#11-chunk-storage`; on finalize, verify every
  expected chunk is present, stream-reconstruct (don't buffer the whole
  file), hash and verify against the client's claimed hash, hand the
  result to `ObjectStore::put`, then delete the temp directory. A partial
  chunk must never leak into `objects/`.
- Engine endpoints: `POST /chunks/write`, `POST /chunks/finalize` (see
  `docs/api.md`).
- Cleanup for abandoned uploads: a sweep (cron-style background task, or
  a call triggered by `scripts/healthcheck.sh`/a scheduled job) that
  deletes `uploads` rows and their temp chunk directories once
  `expires_at` has passed.
- Web: wire the upload UI (from Phase 3) to chunk large files client-side
  and resume on failure — a plain `<input type=file>` + `fetch` chain is
  enough, no need for a library unless the UX genuinely demands it.
- `server/tests/test_uploads.py`: create session → upload chunks
  out of order → complete → verify hash; interrupt (only upload some
  chunks) → resume with the missing ones → complete; finalize with a
  missing chunk is rejected; expired/abandoned sessions get cleaned up.
- `engine/tests/chunk_tests.cpp`: same scenarios at the engine layer.

**Done when:** you can upload a large file, kill the connection partway,
and resume by only sending the chunks that didn't arrive — the final
SHA-256 matches the original file.

**Status:** done — 47/47 `ctest` cases (18 new `ChunkStoreTest`/
`ChunkManagerTest` cases plus 4 new HTTP-level ones in
`EngineServerTest`) and 75/75 `pytest` cases (12 new in
`test_uploads.py`) pass, both lint clean; frontend `tsc`/`eslint`/
`vitest` (11 tests, including a new `uploads.test.ts` with a mocked
`fetch`) and `vite build` all pass too. Notes for whoever picks up
Phase 6:

- **`folder_id` was added to the `uploads` table** — not in
  `docs/architecture.md#database-design`'s original sketch. See
  `app/models/upload.py`'s docstring for why (something has to remember
  where the finished file lands). If Phase 6's `file_versions` table
  needs a similar addition beyond the sketch, document it the same way
  rather than silently diverging.
- **`uploads.received_chunks` is a comma-separated list of indices**, not
  a bare count — also documented in `app/models/upload.py`. The engine's
  on-disk chunk directory (`ChunkStore`) is the real source of truth for
  what's actually stored; this column is a queryable mirror of it so
  `GET /api/uploads/{id}` doesn't need to ask the engine on every status
  check.
- **Two extra endpoints beyond `docs/api.md`'s original three**:
  `GET /api/uploads/{id}` (status/resume — the client needs this to know
  what's missing) and `DELETE /api/uploads/{id}` (explicit cancel). Both
  are documented in `docs/api.md` now. Same reasoning as Phase 3's web
  login screen: added because the stated goal ("resume by only sending
  the chunks that didn't arrive") genuinely needs them, not scope creep
  for its own sake.
- **A missing chunk and a hash mismatch both map to `409`** from the
  engine's `/chunks/finalize` (see `engine_server.cpp`), which
  `EngineClient._post` surfaces as `ObjectCorruptedError` — the same
  exception `/objects/get` uses for a corrupted object. It's a slight
  overload of that name (nothing is "corrupted" in the missing-chunk
  case), but reusing the existing 409-mapped exception avoided adding a
  fourth engine-error type for what `upload_service` treats identically
  either way (a `ConflictError` the client can act on). Revisit if Phase
  6 needs to distinguish them.
- **Cleanup sweep exists but isn't scheduled**:
  `app/services/upload_service.sweep_expired_uploads` deletes expired
  `pending` sessions and their temp chunks, but nothing calls it
  periodically yet (Rule 2 — no cron/scheduler infrastructure was added
  just for this). Wire it to something (a cron job, a management command,
  alongside `scripts/healthcheck.sh`) once this runs somewhere that has a
  scheduler; it's covered by a direct unit test
  (`test_sweep_expired_uploads_removes_only_expired_pending_sessions`) in
  the meantime.
- **Web upload threshold**: `CHUNKED_UPLOAD_THRESHOLD` (20 MiB) and
  `DEFAULT_CHUNK_SIZE` (5 MiB) live in `web/src/api/uploads.ts` — files
  under the threshold still use the plain `POST /api/files/upload` from
  Phase 3/4. `pages/Files.tsx` shows a "Resume upload" button when a
  chunked upload fails partway (`ResumableUploadError` carries the
  session id); resuming re-reads `GET /api/uploads/{id}` and only sends
  what's still missing — not persisted across a page reload/browser
  close, since that would need its own local-storage-backed session
  tracking that nothing has asked for yet (Rule 2 again).
- **Test isolation**: `tests/fake_engine.py`'s `FakeEngineClient` grew
  `write_chunk`/`finalize_chunks`/`abandon_chunks`, mirroring the real
  engine's chunk behavior (including raising `ObjectCorruptedError` for
  both a missing chunk and a hash mismatch, matching the 409 the real
  engine returns for both). `tests/conftest.py`'s `_isolated_storage_root`
  now also patches `app.services.upload_service.get_storage_service` —
  `upload_service` imports that name into its own module namespace, so
  the existing patch on `file_service_module.get_storage_service` alone
  didn't cover it. Any future module that does
  `from app.services.storage_service import get_storage_service` needs
  the same treatment in that fixture.

---

## 6. Phase 6 — Versioning and Trash ✅ done

**Goal:** every overwrite creates a recoverable version; delete is
reversible until explicitly purged.

**Decisions agreed for this phase (follow these over any looser
wording below):**

- **Trigger:** uploading a file with the same name into the same folder
  creates a new version of the existing file (no duplicate, no error).
  Applies to both `POST /api/files/upload` and chunked-upload completion.
- **Retention:** every version is kept until the file is permanently
  purged. No automatic pruning.
- **Restore:** restoring an old version creates a *new* current version
  pointing at the old content; history is never rewritten.
- **Purge:** permanent delete removes the file and its version rows, then
  asks the engine to delete an object only if **no other file or version**
  still references that content hash.
- **Trash expiry:** none — manual purge only (no scheduler exists yet).
- **Trash restore clashes:** if the original folder no longer exists,
  restore to the root; if the name is taken in the target folder, append a
  suffix: `name (restored).ext`.
- **Folders:** files only go to trash. Empty-folder hard delete is
  unchanged.
- **Web UI:** Phase 6 ships a *plain* UI — a Trash page (list, restore,
  delete forever) and a version list per file (download, restore) using the
  existing minimal `window.prompt`/`confirm` style. Polished modals come in
  the Phase 17 redesign. A usable app in hand beats a pretty one later.

- `server/app/models/file_version.py`: per
  `docs/architecture.md#database-design`. Migration.
- `server/app/schemas/versions.py`.
- `server/app/services/version_service.py`: on every file content change,
  create a new `FileVersion` row (bump `version_number`, point
  `files.current_version_id` at it) instead of overwriting; never delete
  an object referenced by any surviving version (this composes with
  Phase 4's dedup reference counting — check it before removing anything).
- `server/app/api/versions.py`:
  `GET /api/files/{id}/versions`,
  `POST /api/files/{id}/versions/{version_id}/restore` (creates a *new*
  current version pointing at the old content — don't mutate history).
- Trash: Phase 3 already sets `deleted_at` on delete. Add the listing/
  restore/purge endpoints — there's no dedicated trash router in the
  initial skeleton; add one (`server/app/api/trash.py` or fold into
  `files.py`, your call) with
  `GET /api/trash`, `POST /api/trash/{id}/restore`, `DELETE /api/trash/{id}`
  (permanent delete — only now does an object become GC-eligible).
- Web: version history UI on a file's detail view (list, view, restore),
  a Trash page (list, restore, permanently delete).
- `server/tests/test_versions.py`: upload → modify → verify 2 versions
  exist → restore v1 → current content matches v1 while v2 stays
  recoverable; delete → appears in trash, not in normal listing →
  restore → reappears; permanent delete removes it for good and (if
  nothing else references the object) frees the underlying bytes.

**Done when:** the Phase 1 spec's steps 11–15 (modify, verify new
version, restore old version, delete, restore from trash) all work
end-to-end through the web UI.

**Status:** done — 114/114 `pytest` (on SQLite *and* a real PostgreSQL 16),
`ruff` clean, frontend `tsc`/`eslint`/`vitest` (28 tests)/`vite build`
clean. Migration `0004` was run against real PostgreSQL with pre-existing
rows (backfill, downgrade and re-upgrade all verified). **Not verified:** a
full `docker compose up` plus clicking through the new UI in a browser —
do that on the first real deploy (Phase 9). The C++ engine was not touched,
so `ctest` was not re-run. Notes for whoever picks up the next phase:

- **A file's identity for versioning is `(owner, folder, name)`** among
  *live* files (`version_service.find_live_file`). Uploading that name adds
  a version; renaming/moving a file onto an occupied name is a `409`
  (`file_service.update_file`); a trashed file doesn't count, so uploading
  over a trashed name makes a brand-new file. Identical bytes under the same
  name are a deliberate no-op (no empty version). Sync (Phase 7) should
  lean on this: "same path" means "same file".
- **`files.content_hash`/`size`/`storage_key` mirror the current version**;
  `files.current_version_id` is the server-side version pointer a sync
  client should compare. It has no FK (circular), and `File`/`FileVersion`
  have no ORM `relationship()` — so deletes must be ordered by hand
  (`db.flush()` the versions before the file, see `trash_service.purge_file`;
  skipping it passed on SQLite and failed on Postgres).
- **Beyond the sketch:** `file_versions.restored_from_version` (which older
  version a restore copied) is not in `docs/architecture.md`'s table.
- **`delete_folder` detaches trashed files** (`folder_id = NULL`) so they
  restore to the root instead of tripping the foreign key.
- **Test isolation, again:** `tests/conftest.py` now patches
  `trash_service.get_storage_service` too (same trap as Phase 5's note) —
  any new service that imports it needs the same line. And
  `TEST_DATABASE_URL=postgresql+psycopg2://…` runs the whole suite on a real
  disposable Postgres; use it whenever you add constraints, FKs or deletes,
  because SQLite doesn't enforce foreign keys.
- **Fresh Postgres + Alembic:** use `scripts/migrate.sh` (or pre-create the
  wide `alembic_version` table) — `docs/errors.md` explains why; plain
  `alembic upgrade head` fails on revision `0002`.
- **Known gaps (deliberate):** no "empty trash" button; orphaned objects
  from a failed delete/upload are never swept (Phase 15 GC); the purge
  reference check can race a concurrent identical upload (documented in
  `trash_service.py`); the UI is plain `prompt`/`confirm` until the Phase 17
  redesign.

---

## 7. Phase 7 — Desktop Sync ✅ done

**Goal:** a client program that mirrors a local folder against the
server. Runs on a user's own machine — it talks to the **Python API
only**, over whatever network reaches the server (LAN or Tailscale). It
never talks to the C++ engine directly: the engine is Docker-internal
only (`docs/security.md#the-engine-boundary`), and the client isn't
necessarily on the same host as the server.

- `client/requirements.txt`: something like `httpx`, `watchdog`,
  `sqlite3` (stdlib), `pydantic`.
- `client/cloudsync/config.py`: server URL, credentials/token storage,
  local sync folder path.
- `client/cloudsync/database.py`: local SQLite schema per
  `docs/synchronization.md#desktop-client-architecture` (`local_path`,
  `file_id`, `content_hash`, `server_version`, `local_modified_time`,
  `sync_status`).
- `client/cloudsync/watcher.py` (filesystem events, e.g. via `watchdog`),
  `scanner.py` (initial/periodic full scan to catch missed events),
  `hasher.py` (SHA-256 — can just shell out to hashlib, no need to touch
  the C++ engine from here).
- `client/cloudsync/api.py`: thin HTTP client against the Phase 2–6
  backend endpoints (auth, files, versions).
- `client/cloudsync/uploader.py`, `downloader.py`: push/pull file
  content, using the chunked upload API from Phase 5 for large files.
- `client/cloudsync/reconciler.py`: implements the algorithm in
  `docs/synchronization.md#sync-algorithm` — detect event → debounce →
  hash → compare local vs. server metadata → classify (local-only,
  server-only, both) → upload/download → update local state.
- `client/cloudsync/queue.py`: durable pending-operation queue backed by
  the local SQLite DB (must survive a restart — Phase 8 depends on this).
- `client/cloudsync/main.py`: wires it all together, runs the watcher +
  reconciler loop.
- `client/tests/`: unit tests per module, plus an integration test that
  runs the reconciler against a fake/local server fixture.
- The C++ `engine/include/sync/*.hpp` headers are there for optional
  server-side primitives (e.g. if you want hashing/conflict comparisons
  done in the engine rather than the client). Given the engine boundary
  constraint above, expect most sync/version logic to actually live in
  `server/app/services/version_service.py` (Phase 6) and the client
  itself — don't force engine involvement where a Python comparison of
  `server_version` vs. the DB's `current_version_id` is simpler. Keep the
  C++ surface small either way (Rule 4).

**Done when:** installing the client, pointing it at a running server,
and syncing a folder mirrors files both ways, matching Phase 1 spec steps
16–17.

**Status:** done and verified — see `client/README.md` (user guide + module map),
`docs/synchronization.md` (design) and `client/cloudsync/reconciler.py` (the
exact decision table). 136 client tests (unit + integration against the real
server app in process) plus a real end-to-end run of the actual CLI against
the Docker stack (24/24: 25 MB chunked upload, two devices, conflict, a real
proxy outage, trash on both sides, `run` mode). Notes for whoever extends it:

- **Server contract added for sync:** `GET /api/sync/snapshot`,
  `POST /api/sync/folders`, and `base_version_id` (conditional write) on
  upload, chunked-upload sessions and delete; `FileResponse.current_version_id`.
  Don't weaken the conditional-write 409: it is what makes conflict detection
  atomic.
- **State lives in `<sync folder>/.cloudsync/state.db`** (base entries, a
  persisted queue, resumable-upload sessions). Every cycle is recomputed from
  disk + that database, so the queue is bookkeeping and status — correctness
  never depends on it.
- **The integration tests import `../server`** (they need the server's
  requirements installed too). `tests/conftest.py` has a `Network` wrapper that
  can drop connections, return HTTP errors and run a hook just before a request
  — use it to reproduce races and outages.
- **Not done (listed in `client/README.md` too):** folders are never deleted
  automatically; renames/moves are delete + create (the bytes are re-sent);
  server changes are found by polling; each cycle fetches the whole snapshot;
  no bandwidth limit, selective sync or tray icon; the Windows/macOS/Linux
  autostart is documented, not packaged. The client was developed and tested on
  Windows; the Linux/macOS paths (config dir, permissions) are covered by unit
  tests but have not been run on those systems.

---

## 8. Phase 8 — Offline + Conflicts ✅ done

**Goal:** the client keeps working when the server is unreachable, and
divergent concurrent edits never silently clobber each other.

- `client/cloudsync/queue.py`: on a failed API call, mark the operation
  queued instead of failing the whole client; retry on reconnect (see
  `docs/synchronization.md#22-offline-mode`).
- `client/cloudsync/conflicts.py`: implements
  `docs/synchronization.md#23-conflict-detection` — when both local and
  server changed since the last common version, do **not** overwrite
  either; write a conflict copy (`name.conflict-<ISO-date>.ext`) and
  leave both the original and the copy for the user to resolve. No CRDTs,
  no automatic merging — that's explicitly out of scope
  (`docs/architecture.md#explicit-non-goals`).
- `client/cloudsync/reconciler.py`: extend to detect the "both changed"
  case specifically (not just "server changed" or "local changed").
- `client/tests/`: server-down → local edit → reconnect → queued edit
  uploads; concurrent edit on both sides → conflict copy created, no data
  lost; process restart mid-queue → queue survives and resumes.

**Done when:** Phase 1 spec steps 18–23 (disconnect, edit locally,
reconnect, verify sync; edit both sides, verify a conflict copy appears)
all pass.

**Status:** done together with Phase 7 (they share the same code). Verified
for real by stopping the proxy container (offline), editing, restarting it,
and watching the queued work upload; and by editing the same file on two
devices (the conflict copy appears on both, neither edit is lost). The
integration tests also cover: a dropped connection midway (nothing lost or
duplicated), an interrupted 8-chunk upload resuming with only the missing
chunks (also across a client restart), stale-base races for uploads and
deletes, a file changing between scan and upload, per-file back-off, token
refresh and a dead login.

---

## 9. Phase 9 — Remote Access (prepared and verified; hardware step pending)

**Goal:** deploy to the real target hardware, reachable remotely.

Follow [`docs/deployment.md`](deployment.md) — it already has the
checklist (Docker + Compose plugin, `.env` with real secrets, Ethernet,
`docker compose up -d --build`, Tailscale install, the provided
`deployment/systemd/personal-cloud.service` unit). Mostly infra work, not
code — the main things to double check:

- `deployment/Caddyfile` routes match whatever endpoints exist by this
  point (it already proxies `/api/*`, `/s/*` to the backend and
  everything else to the frontend — extend if you added top-level routes
  outside those prefixes).
- `JWT_SECRET` and DB credentials in the real `.env` are strong and unique
  — never the `.env.example` defaults.
- Confirm the engine port is still not published anywhere (`docker-compose.yml`'s
  `engine` service should stay on `expose`, never `ports`).

**Done when:** Phase 1 spec step 24 (access the server remotely through
Tailscale) works from a second device.

**Status:** everything that can be done without the target laptop is done
and was verified by building and running the whole stack in an isolated
Compose project (`-p pcverify`, own ports/secrets/volumes). What changed and
why is in the `feat(deploy)` / `feat(ops)` commits and in
[`docs/deployment.md`](deployment.md); the short version: production
compose (only the proxy publishes a port, static nginx web image, required
secrets, healthchecks), migrations on backend start, `scripts/setup.sh` →
`scripts/deploy.sh` (with `scripts/preflight.sh`), verified backups, systemd
units. Verified: fresh build, fresh-DB and upgrade migrations, a 24-check
smoke test through the proxy (incl. a 30 MB chunked upload), container
destroy/recreate, backup → wipe all volumes → restore. **Still to do on the
real machine:** run `scripts/deploy.sh`, install Tailscale, open the app from
a second device, `sudo deployment/scripts/install-systemd.sh` (the systemd
units are untested — no systemd here), and set `BACKUP_COPY_TO`. Whatever
breaks there belongs in `docs/errors.md`.

---

## 10. Phase 10 — Hardening (10-lite done)

**Goal:** production-readiness polish.

- Rate limiting on auth and upload endpoints (a small FastAPI middleware
  is enough — no need for a heavyweight dependency unless the simple
  version proves insufficient).
- Security headers middleware (HSTS, X-Content-Type-Options, etc.) — Caddy
  can also set most of these at the reverse-proxy layer.
- Review `server/app/core/logging.py` against
  `docs/security.md#logging` — confirm nothing sensitive leaks into logs
  as new phases added new log statements.
- Automate `scripts/backup.sh` on a schedule (cron or a systemd timer
  alongside `deployment/systemd/personal-cloud.service`); actually run
  `scripts/restore.sh` against a scratch environment and confirm the
  restored data matches — Phase 1 spec steps 25–28.
- Health monitoring: point an uptime checker (or a simple systemd timer
  running `scripts/healthcheck.sh`) at `/api/health`; decide what happens
  on repeated failure (alerting is out of scope unless you want it — this
  is a personal project, keep it proportionate).
- Failure recovery: verify the failure-case tests from Rule 6 across
  every phase still pass after hardening changes (disk full, corrupted
  object, interrupted upload, etc.).

**Done when:** the full Definition of Done workflow below passes, start
to finish, on the real deployed server.

**Status — "10-lite" (the Milestone 1 subset) is done:** auth rate limiting
(`app/core/rate_limit.py`, login/register/refresh, per client IP), nightly
backup + 5-minute health systemd timers, verified backups with checksums and
retention, and the abandoned-upload sweep now runs on its own
(`app/core/maintenance.py`). **Not done (Milestone 2 / before a public
release):** security headers, a logging review against `docs/security.md`,
rate limits on upload endpoints, encryption of backups, alerting, and a
full Rule-6 failure-recovery pass.

---

## 11. Final Definition of Done

The project is finished when this entire workflow works, against the
real deployed system (not just `docker compose up` on a dev machine):

1. Start the server.
2. Open the web interface.
3. Register/login.
4. Create folders: `MyCloud/Research/`, `Projects/`, `Photos/`.
5. Upload a large file.
6. Interrupt the upload.
7. Resume the upload.
8. Verify the final SHA-256 hash.
9. Upload the same content again.
10. Verify physical storage does not duplicate it.
11. Modify the file.
12. Verify a new version exists.
13. Restore an older version.
14. Delete a file.
15. Restore it from trash.
16. Install the desktop sync client.
17. Sync a local folder.
18. Disconnect the server.
19. Modify a local file.
20. Reconnect.
21. Verify synchronization.
22. Modify the same file independently on two sides.
23. Verify a conflict is detected.
24. Access the server remotely through Tailscale.
25. Run a backup.
26. Destroy/recreate containers.
27. Restore the backup.
28. Verify files and metadata remain intact.

When you land a phase, update this file's "Current state" section (§1)
and `README.md`'s "Project status" section to reflect it — keep the
documentation honest for whoever (human or agent) picks this up next.

---

## 12. Extended roadmap (Phases 11–18)

The product vision grew into an open-source, self-hostable Google Drive
alternative: activity/favorites/quotas, sharing and comments, 2FA (TOTP +
passkeys), Meilisearch search with thumbnails/previews, self-hosting release
tooling, mobile API support, a Drive-style web redesign, and a native mobile
app. The full phase list, the intended execution order
(**Milestone 1, "daily driver":** `6 → 9 → 10-lite → 7 → 8 → 16 → 18a`, where
16 is mobile API support and 18a is background phone-folder sync;
**Milestone 2, luxuries:** `11 → 15 → 12 → 14 → 13 → 17 → 18b`), and the "usable app
ASAP, luxuries later" strategy are in
[`docs/architecture.md`](architecture.md#extended-roadmap-phases-1118).
Meilisearch is the one approved addition to the stack; everything else in
the non-goals list still stands. Detailed per-phase handoff sections are
added here as each phase lands.

### Milestone 2 slice — library, viewers and the redesigned clients (built)

Built out of order on purpose, because it is what makes the daily-driver apps pleasant to use:

- **Server:** `app/api/media.py` (media tokens, inline content with Range, thumbnails),
  `app/api/library.py` (photos timeline, recents, favorites, usage, activity),
  `thumbnail_service.py` (Pillow; static ffmpeg for video, only for sniffed MP4/MOV/WebM/MKV),
  `media_cache.py`, `quota_service.py` (quota enforced on every upload path), `activity_service.py`,
  migration `0006` (`files.taken_at`, `uploads.taken_at`, `favorites`, `activity`). Upload limits
  were tightened (see `docs/security.md`). 206 tests.
- **Web:** Drive-style shell, photo timeline (`/photos`), favorites, recent, activity, a viewer for
  images (zoom/pan), video, audio, PDF and text (HTML shown as escaped text), an upload **queue**
  with per-byte progress, speed, ETA, retry and cancel, and four themes (light, dark, and two retro
  monospace black-and-white ones). Themes work by remapping Tailwind's colour scales to CSS
  variables (`web/src/index.css`), so every component follows the active theme. 56 tests.
- **Android:** queue screen (now / up next / recently finished, live bars, speed, ETA), three
  parallel uploads, small files hashed only on a name clash, Files and Photos tabs with
  thumbnails, built-in viewers (image, video, audio, PDF, text; another app only for formats it
  does not know), the same four themes, a full activity log. 21 unit tests; verified on an emulator
  against the real server.
- **Dates and folders:** `files.modified_at` (the device's own date; migration `0008`) is sent on
  upload and fixable with `PATCH /api/files/{id}`; the Android app derives it from the file name,
  then the taken date, then the file's mtime, and runs a catch-up pass for files backed up earlier.
  Android also has a folder chooser and re-uploads edited photos. Default quota is now 400 GiB
  (migration `0007` raises existing accounts; set `DEFAULT_STORAGE_QUOTA_BYTES` in `.env` too).
- **Not done:** sharing, 2FA, content search (Meilisearch), the rest of Phases 12-15, bulk
  select/move in the web UI, folder upload, video transcoding. The independent security test has
  not run. Android is a debug build, not yet used on a physical phone for days.

### 0.5.0 — fast photos, public links, the phone app's own look (built)

- **Public links:** `scripts/enable-public-links.sh` (Tailscale Funnel / Cloudflare, `--status`, `--off`,
  `--dry-run`; tested with stub binaries in `server/tests/test_enable_public_links_script.py`), the
  `X-Choud-Door` header set by the public door, `instance_settings` table (migration 0016) with the
  kill switch, `GET /api/instance`, `PUT /api/admin/public-links`, `POST /api/shares/revoke-all`,
  `GET /s/_health`; web Server page panel; share responses carry `public_status`.
- **Photo speed:** `files.thumbhash` (migration 0017, `thumbhash.py`), WebP thumbnails,
  `GET /api/thumbs/{id}` (immutable, ETag), `POST /api/media/thumbs` (batch frames),
  `GET /api/library/index` (delta + 304). See `docs/mobile-perf.md`, `docs/api.md`.
- **Android:** own `Sheets`/`Page`/list-row kit (no AlertDialog anywhere), More hub, viewer action bar,
  `LibraryDb` + `Library.sync`, `ThumbLoader.loadPhoto` batching, merged phone-only photos
  (`LocalMedia`), search, upload/share-into-Choud, trash, shared links, storage, sign-in history,
  `WarmCacheWorker`, lazy tabs, plain prefs + lazy encrypted tokens. Test traps: Python needs
  `pip install -r server/requirements.txt pytest ruff`; ruff-format only the files you touch.
- **Still not done:** two-way folder sync on the phone, fast-scroll date thumb, HTTP/2 (needs HTTPS),
  tablet layout, real-phone testing, iOS.

### Phase 16 (mobile API) and 18a (phone sync) — status

- **Server side is done:** the snapshot has an `ETag`/`304` so polling is nearly
  free; conditional writes, resumable chunked uploads and token refresh already
  existed. Nothing else on the server blocks a phone client.
- **Platform decided: Android.** A first slice of the app exists in `android/`
  (Kotlin; login, background camera-roll backup, resumable uploads; 11 unit
  tests; verified end-to-end on an emulator against the Docker stack, incl. a
  30 MB chunked upload). **Not run on a physical phone yet.** Two-way
  folder sync and browsing are not built. Earlier note: [`docs/mobile.md`](mobile.md) is the full spec: the server contract,
  the platform-specific problems (same-name photos from two phones, background
  limits, scoped storage), a platform comparison with a recommendation, and a
  build order.
