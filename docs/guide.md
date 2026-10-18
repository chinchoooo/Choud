# Choud: the complete guide

This is the one document that explains the whole system, from "what is it" down to "which file does
what" and "why was it done this way". It is written so you can learn Choud from zero, or hand it to
someone (or an AI) who has never seen it. The shorter, topic-specific documents it links to go deeper
on one area each:

| Topic | Document |
| --- | --- |
| Philosophy, phases, rules, non-goals | [`architecture.md`](architecture.md) |
| Object storage, dedup, chunks, GC | [`storage.md`](storage.md) |
| Desktop sync algorithm and conflicts | [`synchronization.md`](synchronization.md) |
| Every HTTP endpoint | [`api.md`](api.md) |
| Threat model and controls | [`security.md`](security.md) |
| Running it on real hardware | [`deployment.md`](deployment.md) |
| Real bugs met in deployment and their fixes | [`errors.md`](errors.md) |
| Android app design notes | [`mobile.md`](mobile.md) |
| Releases and the signing key | [`releases.md`](releases.md) |
| Brand assets | [`branding.md`](branding.md) |
| A prompt to learn it, or to keep building it | [`ai-prompt.md`](ai-prompt.md) |

Numbers in this guide (test counts, limits) describe version 0.4.0.

---

## 1. What Choud is

Choud is a **self-hosted Google Drive alternative**. One spare Linux machine at home runs the server.
Everything else (a browser, an Android phone, Windows/Linux/macOS laptops) talks to it over HTTP,
usually through Tailscale (a private VPN between your own devices) or your home network.

What it does:

- Stores files and folders, with **resumable uploads**, **duplicate-free storage** (the same bytes are
  stored once), **versions** of every file, and a **trash**.
- Shows photos on a timeline, previews images/video/audio/PDF/text with built-in viewers, makes
  thumbnails.
- **Searches** file names and the text inside documents.
- **Shares** files and folders by public link (expiry, password, view-only or "add and edit").
- Backs up a **phone** (Android) and **laptops** (desktop client) automatically.
- Supports several people on one server (invites, quotas) and optional two-factor login.

What it deliberately is not (the non-goals, from `architecture.md`): not a cluster, not Kubernetes, not
microservices, no real-time collaborative editing, no automatic merging of conflicting edits, no
per-user sharing between accounts (links are the only way to share), no public cloud dependency. It is
one machine, one operator, with the smallest set of moving parts that does the job.

### The hard rules the code follows

These come from `architecture.md` and explain many decisions you will meet later:

1. **Never silently destroy data.** When unsure: keep the data, return an error, log it. Deletes go to
   trash, overwrites become versions, conflicts keep both copies.
2. **Do not over-engineer.** No dependency or abstraction without a concrete reason.
3. **Keep the responsibilities separate.** Python = API, accounts, metadata, business logic. C++ =
   hashing, bytes on disk, chunks. React = the web UI. The desktop client = the local filesystem.
4. **Keep the C++ API tiny:** only what the Python backend actually calls.
5. **Test failure cases**, not just success (disk full, corrupt object, dropped connection, bad token,
   conflicting edits).
6. **Never commit secrets.**

---

## 2. The system at a glance

```
 Browser (React)      Android app (Kotlin)      Desktop client (Python)
        \                    |                         /
         \                   |  HTTP over Tailscale or LAN
          v                  v                        v
        +-------------------------------------------------+
        |  Caddy reverse proxy   (the ONLY published port) |
        |   /api/*  /s/*  -> backend      everything else -> web (static)
        +------------------------+------------------------+
                                 |
                  +--------------v--------------+
                  |  backend: FastAPI (Python)   |
                  |  auth, files, versions,      |
                  |  sharing, search, sync API,  |
                  |  background loops            |
                  +------+---------------+------+
                         |               | internal Docker network only
          +--------------v---+      +----v-----------------------+
          |  PostgreSQL 16   |      |  engine (C++)               |
          |  metadata, users,|      |  hashing, object store,     |
          |  versions, shares|      |  chunk assembly             |
          |  search text     |      +-------------+---------------+
          +------------------+                    |
                                  shared volume:  STORAGE_ROOT  (objects/, uploads/, raw/ staging,
                                  thumbs/, previews cache)
```

**Five containers** (see `docker-compose.yml`): `postgres`, `engine`, `backend`, `frontend` (a static
nginx serving the built React app), and `proxy` (Caddy). Only `proxy` publishes a port. The engine and
the backend share one Docker volume so they can pass **file paths** to each other instead of streaming
bytes over HTTP.

### Trust boundaries (who is allowed to call whom)

- **Internet / LAN / Tailscale -> Caddy.** Untrusted. Caddy caps request body sizes per route and
  forwards.
- **Caddy -> backend.** The backend authenticates every `/api/*` call (JWT bearer token) except login,
  register, health, and the public share pages (`/s/*`), which have their own token/password checks.
- **Backend -> engine.** Trusted, internal-only. The engine has **no authentication** on purpose: it
  must never be reachable from outside. That is why it is `expose`d, never `ports`-published.
- **Backend -> PostgreSQL.** Trusted, internal.

---

## 3. A tour of the repository

```
server/        Python backend (FastAPI + SQLAlchemy + Alembic)
  app/main.py            builds the app, registers routers, error handlers, background loops
  app/api/               HTTP layer: one file per feature (auth, files, folders, uploads, versions,
                         trash, library, media, shares, public_shares, invites, two_factor, search,
                         sync, health, rewind, insights, archive, admin)
  app/services/          business logic (the real work lives here, not in api/)
  app/models/            SQLAlchemy tables
  app/schemas/           Pydantic request/response shapes
  app/core/              config, DB session, security (JWT, Argon2), TOTP, rate limiting, logging,
                         maintenance loop, custom GUID column type
  app/cli.py             `python -m app.cli gc | index`
  migrations/versions/   Alembic migrations 0001-0015
  tests/                 pytest suite (uses an in-memory SQLite DB and a fake engine)
engine/        C++ storage engine (CMake, Boost.Beast HTTP, OpenSSL, GoogleTest)
  src/hashing  streaming SHA-256         src/storage  object store + manager
  src/chunks   chunk store + manager     src/api      small HTTP server (engine_server.cpp)
  include/sync/  placeholder headers only (see "Known gaps")
web/           React + TypeScript + Vite + Tailwind + TanStack Query
  src/api/               typed fetch wrappers, one per backend area
  src/pages/             Files, Photos, Collections (favorites/recent/activity), Trash, Shares,
                         Invites, Security, Login, Register, Dashboard, Rewind, Space, Server, Vault
  src/vault/             client-side encryption (WebCrypto) and the vault's storage layer
  src/components/        AppShell, FileCollection, FileViewer, ShareDialog, UploadPanel, Logo, ...
  src/uploads/           upload queue (context + chunking/resume logic)
  src/theme/             4 themes via CSS variables (retro is the default)
android/       Kotlin app, programmatic views (no XML layouts, no Compose)
client/        Python desktop client `cloudsync` (sync mode + backup mode)
deployment/    Caddyfile, systemd units (backup timer, health timer, boot unit)
scripts/       setup, preflight, deploy, backup, restore, healthcheck, gc, notify, brand assets
docs/          this guide and the topic documents
choud-brand-assets/   the supplied logo kit (source of truth for branding)
```

Rule of thumb for finding code: **an endpoint lives in `server/app/api/<feature>.py`, its logic in
`server/app/services/<feature>_service.py`, its table in `server/app/models/`, its test in
`server/tests/test_<feature>.py`.**

---

## 4. The data model (PostgreSQL)

All primary keys are UUIDs, created through a custom `GUID` column type that works on both PostgreSQL
(native UUID) and SQLite (used by tests). **Use `GUID()` for any new key column.**

| Table | Purpose | Notable columns |
| --- | --- | --- |
| `users` | accounts | `username`, `email` (unique), `password_hash` (Argon2id), `is_active`, `storage_quota` (bytes), `totp_secret`, `totp_enabled`, `totp_last_step`, `totp_failures`, `totp_locked_until` |
| `folders` | folder tree per user | `owner_id`, `parent_id` (null = root), `name` |
| `files` | one row per logical file | `owner_id`, `folder_id`, `name`, `mime_type`, `size`, `content_hash` (SHA-256 of the **current** content), `storage_key`, `current_version_id`, `taken_at` (photo taken), `modified_at` (device's own date), `deleted_at` (non-null = in trash) |
| `file_versions` | every version of every file | `file_id`, `version_number`, `content_hash`, `size`, `restored_from_version`, `created_by` |
| `uploads` | resumable chunked upload sessions | `file_name`, `file_size`, `chunk_size`, `total_chunks`, `received_chunks` (comma-separated indexes), `expected_hash`, `base_version_id`, `status`, `expires_at`, `folder_id`, dates |
| `favorites` | a user's starred files | `(user_id, file_id)` |
| `activity` | audit trail shown in the UI | `user_id`, `action`, `file_name`, `detail` |
| `shares` | public links | `token` (256-bit, unique), `file_id` xor `folder_id`, `permission` (`view`/`edit`/`drop`), `max_downloads`, `password_hash`, `expires_at`, `revoked_at`, `download_count` |
| `invites` | single-use sign-up codes | `code`, `created_by`, `storage_quota`, `expires_at`, `used_by`, `used_at` |
| `recovery_codes` | two-factor recovery | `user_id`, `code_hash` (SHA-256), `used_at` |
| `file_text` | extracted text for content search | `file_id`, `content_hash`, `status` (`ok`/`skipped`/`failed`), `text` |
| `login_events` | an account's sign-in history | `user_id`, `at`, `ip`, `user_agent`, `success`, `new_device` |

Invariants worth knowing (each is enforced by code and covered by a test):

- A **file's identity for versioning is `(owner, folder, name)` among live files.** Uploading the same
  name into the same folder adds a version; identical bytes are a no-op; a trashed name does not count.
- `files.content_hash/size/storage_key` always **mirror the current version**. `current_version_id` has
  no foreign key (it would be circular) and `File`/`FileVersion` have no ORM `relationship()`, so
  deletes are ordered by hand (flush versions, then the file) or PostgreSQL rejects them.
- **Reference counting lives in PostgreSQL, not in the engine.** An object on disk may be deleted only
  when no file and no version of any user references its hash.
- Folder names are unique per `(owner, parent)` by an application check, not a database constraint
  (a NULL parent in a unique index behaves inconsistently across databases).
- Folder delete is a hard delete and only for **empty** folders; files only go to trash.
- A share has exactly one target (a check constraint).

Migrations are Alembic files `0001`..`0015` (users, folders+files, uploads, versions, upload base
version, library features, quota raise, `modified_at`, shares, share permission, invites, two-factor,
file text, drop links + download limits, login events). They run **automatically when the backend container starts** (`entrypoint.sh`). On a brand
new PostgreSQL use `scripts/migrate.sh` by hand (it pre-creates a wide `alembic_version` table; see
`errors.md` for why).

---

## 5. The storage engine (C++) and how bytes are stored

### Content addressing

A stored object is named by the **SHA-256 of its bytes**. The engine keeps objects under
`STORAGE_ROOT/objects/<first two hex chars>/<full hash>`; the two-character prefix is a *shard*
directory so no single folder gets millions of entries. Consequences:

- **Deduplication is automatic.** Uploading identical bytes twice stores one object; two `files` rows
  (or two versions) simply point at the same hash.
- **Integrity is checkable.** Re-hashing an object proves it is intact; a corrupted or missing object is
  reported as an error instead of being served.
- Names, folders and owners are *metadata* in PostgreSQL; the engine knows nothing about them.

### The engine's HTTP API (internal only)

`GET /health`, `POST /hash`, `POST /objects/exists | put | get | delete`,
`POST /chunks/write | finalize | abandon`. Bodies are small flat JSON objects, parsed by a tiny
hand-written reader (a deliberate choice: only our own trusted processes talk to it).

Because the backend and engine share a volume, requests carry **paths, not bytes**:

- `put` **consumes** its source path (moves the staged file into the store).
- `get` **copies** an object out to a path (the stored object survives).
- Get these two directions right whenever you add an engine call.

### Chunked (resumable) uploads

1. The client creates a session (`POST /api/uploads`) saying file size, chunk size, name, folder,
   expected hash. The server validates (chunk <= 64 MiB, <= 20,000 chunks) and stores a row.
2. The client sends each chunk (`POST /api/uploads/{id}/chunks/{index}`); the exact size is checked and
   the chunk is written under `STORAGE_ROOT/uploads/<id>/NNNNNN` through the engine. Chunks can arrive
   in any order and be re-sent.
3. `GET /api/uploads/{id}` tells a returning client which chunks are missing, so it only re-sends those.
4. `POST /api/uploads/{id}/complete`: the engine verifies every chunk exists, **streams** them together
   (never loading the file into memory), checks the hash, and `put`s the result into the object store.
   A half-finished upload can never appear in `objects/`.
5. Abandoned sessions are deleted (with their chunks) after `expires_at` by the maintenance loop.

### Garbage collection (`gc_service`)

Normal deletes never remove objects except through trash purge (and only if unreferenced). Anything
left over (a crash between steps) is an *orphan*. GC walks `objects/` **read-only**, treats an object as
an orphan only if no file/version references its hash **and** it is older than a grace period (72 h),
and deletes only through the engine. By default it only **reports** (`GC_DELETE_ENABLED=false`); run
`python -m app.cli gc [--delete]` or `scripts/gc.sh` to act.

---

## 6. The life of the important operations

Reading these in order is the fastest way to understand the backend.

### 6.1 Logging in (with optional two-factor)

`POST /api/auth/login {email, password, otp?}` -> checks the Argon2id hash (same error for "no such
user" and "wrong password", so emails cannot be probed) -> if the account has two-factor on and `otp`
is missing, answers `401 {"detail": "two_factor_required"}`; the client then asks for a code and
retries -> issues an **access token** (15 min) and a **refresh token** (7 days), both signed JWTs
carrying a *type* claim so one cannot be used as the other. Refresh rotates both. Logout is stateless:
the client throws its tokens away (a deliberate non-feature: no session table).

Two-factor (`totp.py`, `two_factor_service.py`): standard TOTP (RFC 6238; 30 s, 6 digits, HMAC-SHA1)
using only the standard library, checked against the RFC's test vectors. A code works **once** (last
used step remembered), +-1 window is accepted for clock drift, five wrong codes lock code entry for
15 minutes, ten single-use recovery codes are stored hashed. It is only needed at *login*; clients then
use refresh tokens, so background backup is never blocked by a code prompt.

### 6.2 Who may register

`REGISTRATION_MODE`: `invite` (default; the first account on an empty server is free, then each signup
needs a single-use, expiring code from the administrator = the **oldest account**), `open`, or
`closed`. An unknown value behaves like `invite`. An invite can carry its own quota.

### 6.3 A simple upload (`POST /api/files/upload`)

Multipart form -> `file_service.upload_file`: validate the filename (no slashes, traversal, control
characters) -> read the body in **bounded** chunks (>128 MiB = 413) into a staging file under
`STORAGE_ROOT` -> check the owner's **quota** -> hash and hand to the engine (`put`) ->
`version_service.save_content` decides: new file, new version, or no-op for identical bytes -> activity
log. Names are *never* used to build disk paths; storage keys are server-generated.

### 6.4 Versions, trash, purge

- Every content change makes a `file_versions` row and moves `files.current_version_id`.
- **Restore a version** copies an old version's content into a *new* current version (history is never
  rewritten).
- **Delete** sets `files.deleted_at` (trash). **Restore from trash** returns it to its folder, or the
  root if the folder is gone, renaming to `name (restored).ext` on a clash. **Purge** removes the
  file, its versions and its search text, then deletes each stored object **only if** no other file or
  version still references that hash.

### 6.5 Downloads, previews and thumbnails

- Downloads stage the object out of the engine and stream it, then delete the staging copy.
- Browsers cannot send an `Authorization` header from `<img>`, `<video>` or `<audio>`, so previews use a
  **media token**: a separate short-lived (1 h) JWT type placed in the URL path. It only works on the
  media routes.
- `/api/media/.../content` supports HTTP **Range** (video seeking) and only serves an **allowlist** of
  safe types inline (images, video, audio, PDF, plain text). HTML, SVG and everything else is forced to
  download, with `nosniff` and a locked-down content-security-policy, so an uploaded file can never run
  script in your origin.
- **Thumbnails** (128/256/512/1024 px) are derived data cached under `STORAGE_ROOT/thumbs/` keyed by
  content hash. Images use Pillow (with a pixel limit against decompression bombs). Video frames use a
  pinned static `ffmpeg` and **only** on files whose first bytes prove they are MP4/MOV/WebM/MKV, with
  network protocols disabled.

### 6.6 Search

`GET /api/search?q=` returns `{folders, files, content}`.

- **Names:** substring, case-insensitive, owner-scoped.
- **Contents (Phase 14):** a background loop (`index_loop`, every 60 s, 25 files per pass) finds live
  files whose current content has no up-to-date `file_text` row and extracts text:
  plain text/code in-process (first 5 MB, binary skipped); **PDF and .docx/.pptx/.odt/.ods in a separate,
  resource-limited subprocess** (60 s timeout, 1 GiB memory cap on Linux, zip-bomb guard) because anyone
  with an edit link can upload such files. Non-text types get a cheap `skipped` row; unreadable files a
  `failed` row (never retried until the content changes). On PostgreSQL the query uses full-text search
  (`to_tsvector('simple', ...)`, GIN index, ranked, whole words); SQLite (tests) falls back to substring.
  Results are only served when the stored text matches the file's *current* hash, trashed files and
  other users' files never appear, and snippets are built in Python around the match.
  `python -m app.cli index [--all]` indexes or rebuilds everything now.

### 6.7 Public share links

`POST /api/shares` makes a 256-bit token for **one** file or folder, with optional expiry and password
(Argon2id) and a permission. Visitors need no account: `/s/<token>` is **server-rendered, script-free
HTML** (`share_pages.py`) sent with `default-src 'none'` and friends. Properties:

- A link reaches **only its target**: for a folder, every request is checked by walking the item's
  parent chain up to the shared folder. Other users' items, siblings and the account root are
  unreachable even by guessing ids.
- Unknown, expired, revoked and trashed-target links all return the **same 404**.
- A correct password sets an HMAC-signed, HttpOnly cookie scoped to that one link for an hour; changing
  the password invalidates all earlier unlocks. Unlock attempts are rate limited (10/min/IP).
- **Edit links** (`permission=edit`) add four POST routes: upload (<= 20 files; a same-name file becomes
  a new **version**), make folder, rename, and trash. Every action re-checks the target is inside the
  link, uploads count against the **owner's** quota and size limits, and a "delete" only moves the file
  to the **owner's trash**. Edit actions are rate limited (60/min/IP). A file link with edit permission
  can only upload a new version of that one file.

### 6.8 Desktop sync (two-way mode)

Defined in `synchronization.md` and `client/cloudsync/reconciler.py`. In short, each cycle compares
three views of every path: **local** (disk now), **remote** (`GET /api/sync/snapshot`, cheap thanks to an
ETag/304), and **base** (what both agreed on last time, in the client's SQLite `state.db`). A pure
function `decide(local, remote, base)` returns the action (upload new / upload update / download /
conflict / adopt / delete local / delete remote / forget); every row of its decision table is a unit
test. Safety rules: writes are **conditional** (`base_version_id`, else `409` and the next cycle
resolves it); a **conflict keeps both** (yours becomes `name.conflict-<date>.ext`); an **edit beats a
delete** in either direction; deletes go to a recoverable trash on both sides; downloads are staged,
hash-verified and swapped in atomically; files still being written are skipped; paths are validated so
nothing escapes the sync folder; symlinks are never followed. If the server is unreachable nothing
fails: work stays pending and is recomputed from disk next cycle (the SQLite queue is bookkeeping, not
the source of truth).

### 6.9 Desktop backup mode (Milestone 3)

Same engine, narrowed: `backup_plan()` keeps only uploads/adopt/forget. It never downloads, **never
deletes anything on the server**, and when both sides changed it uploads this machine's file as a new
version. Each configured folder is scoped to `Backups/<computer>/<folder>` on the server through an
API client with a `remote_prefix` (paths are stripped/added transparently), and keeps its bookkeeping in
the settings directory (nothing is written inside your folders). `run_backup_forever` probes
`/api/health` once a minute while the server is unreachable (so it does not scan the disk pointlessly
when Tailscale is off), then backs up every 15 minutes at low CPU/disk priority.
`cloudsync install-service` registers auto-start (systemd user service on Linux, launchd agent on
macOS, a hidden Task Scheduler task on Windows).

### 6.10 Phone backup (Android)

Reads photos/videos through MediaStore for the chosen folders, uploads them under
`<phone name>/<relative path>` with up to 3 uploads in parallel. Small files are **not hashed up front**
(the server hashes anyway): the app only hashes when a name clash needs resolving. After a reinstall
the app fetches the server snapshot and, for any path the server already lists, hashes locally and
**skips the upload when the hashes match**. Dates: each file's date comes from its file name
(`IMG_20250206_160717396.jpg`), else the taken date, else the file's modified time, and a catch-up pass
fixes files that were uploaded before dates were stored. WorkManager schedules periodic runs.

---

### 6.11 The features that set Choud apart (0.4.0)

- **Rewind** (`rewind_service.py`). Every change is already a timestamped version and deletes wait in
  the trash, so the past can be read back. *Browse* shows a folder as it was at time T (files that
  existed, with the content they had); *restore* puts one file, a folder tree, or everything back by
  appending **new versions** (the version you rewind away from stays in history), un-trashing files, and
  **never touching files created after T**. Tree restores preview by default. Use case: a bad sync, an
  accidental mass delete, or ransomware. Limits: names and locations are the current ones, and purged
  files or pruned versions cannot return.
- **File requests and one-time links** (`share_service`, `public_shares`). A `drop` link is an upload-only
  page: the visitor cannot list, preview, download, rename or delete anything, and a clashing name
  becomes `name (2).ext` (never an overwrite). `max_downloads` makes any link die for everyone after N
  downloads (1 = one-time).
- **Space insights** (`insights_service`). What deduplication saved (logical vs stored bytes), what old
  versions cost, a breakdown by type, the biggest files, same-content duplicates, and an explicit
  version pruning (keep the newest N; preview first; the current version always stays; an object leaves
  the disk only when nothing else references it).
- **On this day** (`/api/library/memories`) and a **sign-in history** with new-device flags
  (`security_service`), plus an **administrator server view** (`/api/admin/server`).
- **Vault** (`web/src/vault/`). Client-side encryption: PBKDF2-SHA256 (600k) to AES-256-GCM, 1 MiB
  chunks each sealed under its own IV with the chunk number and a last-chunk flag authenticated;
  names, types and sizes live in an encrypted index (a new *version* on every change). The server holds
  `<random>.cvault` files and cannot read them. No recovery if the passphrase is lost.
- **Bulk actions and zip.** Select several files/folders in the web app to move, delete or download
  as one zip (`archive_service`: built one file at a time on the storage volume, 4 GiB / 5,000 file
  caps). Whole folders can be uploaded by drag-and-drop or the "Upload folder" button.
- **Startup screen.** Steps reflect real events (server reachable, login checked). A server outage no
  longer signs you out: the saved login is kept and a retry is offered.
- **Phone extras.** From the viewer: make a share link (1 day, 7 days, one-time, never expires) and
  keep a file on the phone so it opens without the server (the Files tab then lists kept files when
  the server is unreachable).
- **Desktop client.** An upload speed limit (`cloudsync limit KBPS`).

## 7. The API surface (summary)

Full detail and request/response shapes are in [`api.md`](api.md). Grouped by router:

| Prefix | What |
| --- | --- |
| `/api/auth` | register, login, refresh, logout, me, `registration` (is an invite needed?) |
| `/api/auth/2fa` | status, setup, enable, disable, recovery-codes |
| `/api/files` | list/directory, upload, get, download, patch (rename/move/dates), delete (to trash) |
| `/api/folders` | create, get, rename/move, delete (empty only) |
| `/api/files/{id}/versions` | list, download a version, restore a version |
| `/api/trash` | list, restore, purge |
| `/api/uploads` | create session, status, send chunk, complete, cancel |
| `/api/library` | recent, photos timeline, favorites (+ put/delete), usage, activity |
| `/api/media` | issue media token, content (Range), thumbnail |
| `/api/search` | names + contents |
| `/api/shares` | create/list/update/revoke public links |
| `/s/{token}...` | the public pages: view, unlock, download, thumbnail, and for edit links upload/mkdir/rename/trash |
| `/api/invites` | administrator: create/list/delete sign-up codes |
| `/api/sync` | `snapshot` (the whole tree with versions) and `folders` (ensure a path exists) |
| `/api/health` | database, engine and storage status |
| `/api/rewind` | browse a folder as it was at a past time; restore a file or a whole tree (preview first) |
| `/api/insights` | space report (dedup savings, history cost, duplicates) and version pruning (preview first) |
| `/api/archive/zip` | download a selection of files and folders as one zip |
| `/api/admin/server` | administrator only: disk, counts, search backlog, settings |
| `/api/auth/security-log` | your recent sign-in attempts, with new-device flags |
| `/api/library/memories` | photos and videos from this day in earlier years |

Conditional writes: upload, chunked-upload sessions and delete accept `base_version_id`; if the file is
no longer on that version the server answers **409 with a `version_conflict` code**. Do not weaken
this: it is what makes sync conflict detection atomic.

---

## 8. Security model

Assume the network is hostile, uploaders may be hostile (edit links), and the operator is you.

| Area | What is done |
| --- | --- |
| Passwords | Argon2id; identical error for unknown user/wrong password |
| Sessions | short access tokens, rotating refresh tokens, token *types* (access vs refresh vs media) |
| Two-factor | TOTP, one-time codes, lockout, hashed recovery codes; disabling needs password + code |
| Registration | invite-only by default |
| Authorization | every query filters by `owner_id`; client-supplied owner ids are never trusted |
| Filesystem | names validated; disk paths are server-generated, never built from client text |
| Uploads | bounded reads, exact chunk sizes, quotas on every upload path, Caddy body caps |
| Previews | inline allowlist, `nosniff`, restrictive CSP, Range supported safely |
| Parsing | ffmpeg only on sniffed containers, no network protocols; PDF/Office parsed in a sandboxed subprocess; Pillow pixel cap |
| Public pages | no JavaScript at all, escaped output, uniform 404, password cookies scoped per link |
| Edit links | only trash (never hard delete), versions kept, owner quota, rate limits |
| Rate limits | per client IP: login 10/min, register 10/h, refresh 60/min, 2fa 20/min, share-view 300/min, share-unlock 10/min, share-edit 60/min |
| Engine | never reachable from outside |
| Secrets | `.env` is git-ignored; `deploy.sh` refuses placeholder secrets; Android signing key lives outside the repo |
| Backups | nightly, checksummed, retention, verified by restoring; **encrypted** (AES-256 + PBKDF2) when `BACKUP_PASSPHRASE_FILE` is set |
| Browser headers | strict CSP on the app, `nosniff`, no-referrer, frame denial, permissions policy; baseline headers on API responses |
| Vault | files sealed in the browser (AES-256-GCM, PBKDF2 600k); the server never sees the key, contents or names |
| Sign-in history | attempts on real accounts recorded for a year; new devices flagged |

Honest limits: rate limiting is in memory (one backend process); the TOTP secret is stored as readable
text in the database; encrypted backups protect confidentiality, not authenticity; the Vault cannot
protect against malware on the device you unlock it from; no independent penetration test has been run. See `security.md` for the full list.

---

## 9. Inside the backend

### 9.1 Layers

`api/` (parse the request, call a service, shape the response) -> `services/` (rules and orchestration)
-> `models/` (tables) and `engine_client`/`storage_service` (the C++ engine). Services raise domain
errors (`NotFoundError`, `ConflictError`, `ValidationError`, `QuotaError`, `PayloadTooLargeError`,
`StorageError`, `VersionConflictError`) from `errors.py`; the API layer maps them to HTTP statuses.

### 9.2 Key services

`file_service` (upload/download/rename/move/delete, safe names), `version_service` (the version rules),
`trash_service`, `upload_service` (chunk sessions), `storage_service` + `engine_client` (the only
route to the engine), `quota_service`, `activity_service`, `sync_service` (snapshot), `thumbnail_service`
and `media_cache`, `share_service` + `share_pages` (links and their HTML), `invite_service`,
`two_factor_service`, `index_service` + `text_extract` (search), `gc_service`.

### 9.3 Background work (inside the backend process, no cron container)

- `maintenance_loop` (hourly): delete expired upload sessions and chunks, evict stale preview cache,
  and the daily GC **report**.
- `index_loop` (every 60 s): the content-search indexer.
Failures are logged and retried next interval; housekeeping must never take the API down.

### 9.4 Configuration

All settings are environment variables read by `app/core/config.py` (`.env`; only `.env.example` is
tracked). Main ones: `POSTGRES_*`, `JWT_SECRET` (must be strong; the backend refuses placeholders),
`ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `STORAGE_ROOT`,
`DEFAULT_STORAGE_QUOTA_BYTES` (400 GiB), `REGISTRATION_MODE`, `RATE_LIMIT_ENABLED`,
`MAINTENANCE_INTERVAL_SECONDS`, `INDEX_INTERVAL_SECONDS`/`INDEX_BATCH`, `GC_*`, `ALERT_WEBHOOK_URL`,
`BACKUP_KEEP`, `HTTP_PORT`/`HTTPS_PORT`.

### 9.5 Limits at a glance

Simple upload <= 128 MiB (the clients use it up to 20 MiB); chunk <= 64 MiB (clients send 5 MiB);
<= 20,000 chunks per upload; Caddy caps upload requests at 160 MB and other API bodies at 10 MB;
edit-link upload <= 20 files per request; text indexing keeps <= 1,000,000 characters per file;
default quota 400 GiB.

---

## 10. Inside the web app

React 18 + TypeScript + Vite + Tailwind + React Router + TanStack Query.

- **`api/`**: one small typed module per backend area on top of `client.ts`, which adds the bearer
  token, refreshes it once on a 401, and throws `ApiError`.
- **`auth/`**: `AuthContext` (login with optional two-factor code, register with optional invite code)
  and `ProtectedRoute`. Tokens live in `localStorage`.
- **`components/AppShell`**: sidebar (Lucide icons, `Logo`, storage meter, theme switch), search box,
  Refresh button, upload panel. `FileCollection` renders list/grid; `FileViewer` is the built-in viewer
  (images with zoom/pan, video, audio, PDF, text; HTML shown as escaped text); `ShareDialog`,
  `VersionHistory`, `RowMenu`, `Dialogs`, `QrCode` (drawn as plain SVG).
- **`uploads/`**: an upload **queue** with per-byte progress, speed, ETA, retry and cancel; files over
  20 MiB use chunked, resumable upload (5 MiB chunks).
- **Themes**: `index.css` defines four themes (light, dark, retro black, retro paper) as CSS variables;
  `tailwind.config.js` maps Tailwind's colour scales onto them, so every component follows the theme
  without knowing which is active. **Retro is the default.**
- Listings refresh themselves (every 20 s while the tab is visible) and on the Refresh button.
- 68 Vitest tests; `npm run build`, `npm run lint`, `npx tsc --noEmit`.

---

## 11. Inside the Android app

Kotlin, **programmatic views** (`Ui.kt` builds themed widgets in code; no XML layouts, no Compose),
RecyclerView lists, OkHttp, WorkManager, androidx security-crypto.

- **Screens/tabs:** `MainActivity` (login incl. two-factor field, tab host), `BackupTab` (live queue:
  now/up next/recently finished, bars, speed, ETA), `FilesTab` and `PhotosTab` (thumbnails,
  pull-to-refresh, auto-refresh when stale), `MoreTab` (folders to back up, theme, log, settings),
  `ViewerActivity` (built-in viewers: zoomable image, video, own audio player, PDF via PdfRenderer, text).
- **Engine room:** `Backup.kt` (scan, hash only when needed, 3 parallel uploads, conflict copies,
  dates, reinstall skip), `Api.kt` (HTTP + token refresh, single-flight), `Store.kt` (settings and the
  `BackupDb` SQLite with fingerprints and date flags), `SyncWorker.kt` (WorkManager schedule),
  `Logic.kt` (pure, unit-tested helpers: remote folder naming, selection, `dateFromFileName`),
  `EventLog.kt` (a detailed on-device log for debugging).
- Themes match the web; the launcher icon is an adaptive icon generated from the brand SVGs
  (`scripts/brand/from_sheet.py`).
- 28 unit tests; signed release builds read the key from `~/.personal-cloud-signing/` (outside the repo).

---

## 12. Inside the desktop client (`client/cloudsync`)

A Python package with its own SQLite state. Modules: `api.py` (HTTP, token refresh, optional
`remote_prefix`, reachability probe), `scanner.py` (what is on disk, with a stat cache),
`reconciler.py` (the pure decision table), `syncer.py` (one cycle: scan, snapshot, plan, execute, with
per-action back-off and offline handling; `backup_plan` narrows it for backup mode), `uploader.py` /
`downloader.py` (chunked/resumable upload; staged, verified download), `conflicts.py` (conflict copy
names), `watcher.py` (filesystem events, debounced), `database.py` (base entries, queue, resumable
sessions), `backup.py` (targets, priority, reachability loop), `service.py` (auto-start plans),
`main.py` (CLI: `login`, `sync`, `run`, `status`, `folders`, `install-service`, `uninstall-service`,
`logout`). 150 tests, many of which run the client **against the real server app in process**.

---

## 13. Deploying and operating it

Full guide: [`deployment.md`](deployment.md). The short version on a Linux machine with Docker:

```bash
scripts/setup.sh     # writes .env with strong random secrets
scripts/deploy.sh    # preflight checks, build, start, wait until healthy
```

- **Proxy:** Caddy on port 80 (plain HTTP is right on Tailscale/LAN; swap `:80` for a hostname to get
  automatic HTTPS).
- **Tailscale:** install it on the server and each device; use the server's Tailscale IP or MagicDNS
  name as the address in the apps.
- **systemd** (`deployment/systemd`, `install-systemd.sh`): start on boot, a **nightly backup timer**
  and a **5-minute health timer**.
- **Backups** (`scripts/backup.sh`, `restore.sh`): database dump + object store, checksummed,
  retention (`BACKUP_KEEP`), and restore was proven by wiping all volumes and restoring.
- **Alerts** (`scripts/lib/notify.sh`): optional webhook (ntfy, Discord or Slack) on health/backup
  failures, sent on change plus a periodic reminder.
- **Health:** `GET /api/health` reports database, engine and storage; `scripts/healthcheck.sh` wraps it.
- **Updating:** `git pull && bash scripts/deploy.sh` (migrations run on backend start).
- **Releases:** GitHub Releases carry the signed APK, the Windows `cloudsync.exe` and `SHA256SUMS.txt`
  ([`releases.md`](releases.md)). **Back up the Android signing key**; losing it means every phone must
  uninstall before updating.
- **Dev:** `make dev` (or `docker-compose.dev.yml` + `.env.dev`) for hot reload with placeholder secrets.

---

## 14. Testing

| Suite | Where | Count (0.3.0) | Notes |
| --- | --- | --- | --- |
| Server | `server/tests` | 320+ pass, 1 skipped | in-memory SQLite + `FakeEngineClient`; `TEST_DATABASE_URL=postgresql+psycopg2://...` runs the **whole suite on real PostgreSQL** (do this when adding constraints, FKs or deletes, since SQLite does not enforce foreign keys) |
| Engine | `engine/tests` | 47 (last run before the later features; the engine was not changed since) | GoogleTest via `ctest`: known SHA-256 vectors, put/get/exists/remove, corruption, dedup, chunks, HTTP layer |
| Desktop client | `client/tests` | 153 pass, 3 skipped | unit tests plus integration against the real server app |
| Web | `web/tests` | 100 | Vitest + Testing Library |
| Android | `android/app/src/test` | 28 | pure logic and the API client; the UI was checked by hand on an emulator |

Test-isolation traps (real ones that bit): any module that does
`from app.services.storage_service import get_storage_service` must also be patched in
`tests/conftest.py` so the fake engine intercepts it; rate limits are disabled globally in tests and
enabled per test where they are under test; Windows runs need Git's bash for the script tests.

Commands: `cd server && pytest`; `cd client && pytest`; `cd web && npm run build && npm run lint && npm test`;
`cd android && ./gradlew testDebugUnitTest`; `cmake -S engine -B engine/build && ctest --test-dir engine/build`.

---

## 15. Why it is built this way (decisions you will otherwise question)

- **Two languages.** Python is fast to change for rules and API; C++ owns the hot, byte-level work
  (hashing, assembling chunks) where predictable memory and speed matter. The engine API stays tiny so
  the boundary is easy to reason about.
- **Content-addressed storage** gives dedup and integrity for free, and makes versions cheap (a version
  is a row pointing at a hash).
- **Reference counts in PostgreSQL**, not the engine: the database is the source of truth for "who uses
  this hash", and it can answer across users and versions in one query.
- **Paths, not bytes, between backend and engine** (shared volume): avoids copying every upload over
  HTTP. The price: the two must share a filesystem.
- **Stateless JWT with no revocation list**: simpler; access tokens are short-lived.
- **Server-rendered, script-free public pages**: the safest possible surface for anonymous visitors.
- **Derived data is disposable** (thumbnails, search text, preview cache) and rebuilt on demand.
- **Conditional writes + three-way compare** in sync: conflicts are detected by the server atomically,
  not guessed by clients.
- **No per-user sharing**: links are enough for the real use cases and avoid a permissions system.
- **Hand-rolled TOTP and tiny JSON parser**: small, fully specified, tested against vectors; no
  dependency without a reason.
- **Retro look with modern icons**: a distinctive identity (monochrome, monospace, square) that stays
  legible and accessible.

---

## 16. Known gaps and what to build next

Not built: iOS app; passkeys; comments; per-user sharing (by decision); WebDAV (mounting the drive as
a normal folder); Vault in the Android app and desktop client (it is web-only); video transcoding;
renames/moves in sync are delete+create; the desktop client has no tray icon or selective sync;
Rewind does not record renames/moves; an independent security test; the engine's `include/sync/*`
headers are empty placeholders (all sync logic is in Python on purpose).

Operational to-dos on your own machine: set `REGISTRATION_MODE`, `DEFAULT_STORAGE_QUOTA_BYTES`,
optionally `ALERT_WEBHOOK_URL`; back up `~/.personal-cloud-signing/`; run `python -m app.cli index --all`
once after upgrading so old files become searchable; decide when to turn on `GC_DELETE_ENABLED`.

---

## 17. A learning path

Read in this order; each step is small and builds on the last.

1. `docs/architecture.md` (philosophy and rules), then this guide's sections 2-4.
2. **Follow one upload end to end:** `web/src/uploads/` -> `server/app/api/files.py` ->
   `file_service.upload_file` -> `version_service.save_content` -> `storage_service` ->
   `engine/src/api/engine_server.cpp` -> `storage/object_store.cpp`. Then do the same for a chunked
   upload (`upload_service.py`, `chunks/chunk_manager.cpp`).
3. **Read the sync decision table:** `client/cloudsync/reconciler.py` and `tests/test_reconciler.py`.
4. **Read a security feature and its tests:** `share_service.py` + `tests/test_shares.py`, then
   `test_share_edit.py`.
5. **Run it:** `make dev`, register, upload, create a share link, open it in a private window.
6. **Break it on purpose:** kill the connection during a chunked upload and resume; edit the same file
   on two devices; run `python -m app.cli gc`; restore from a backup.

Exercises: add a new column with a migration (and a test on real PostgreSQL); add a text type to
`text_extract.PLAIN_EXTENSIONS`; add a new endpoint following the api -> service -> model -> test
pattern; add a rate limit to a route and a test that enables it.

### Glossary

**Object**: a stored blob named by its SHA-256. **Dedup**: storing identical bytes once. **Shard**:
the two-character directory under `objects/`. **Chunk**: one piece of a resumable upload.
**Version**: a row recording one content of a file. **Snapshot**: the server's whole tree as the sync
client sees it. **Base**: what client and server last agreed on. **Conflict copy**: the extra file
kept when both sides changed. **Media token**: a short-lived URL token for previews. **Edit link**: a
share link that allows adding and changing files. **GC**: garbage collection of unreferenced objects.
**TOTP**: the 6-digit code from an authenticator app. **Tailscale**: the private VPN between your
devices.
