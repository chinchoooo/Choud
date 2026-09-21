# API Reference

Base URL: `http://<host>:8000` in development, or through the reverse
proxy in production (see [`deployment.md`](deployment.md)).

## Implemented

### `GET /api/health`

Checks the API process, the PostgreSQL connection, the C++ engine, and
storage availability.

```json
{
  "status": "healthy",
  "database": "healthy",
  "engine": "healthy",
  "storage": "healthy"
}
```

Returns `200` when every component is healthy, `503` otherwise.

### Auth

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
GET  /api/auth/me
```

`POST /api/auth/register` — `{username, email, password}` → `201` with the
new user (never the password or its hash). `409` on a duplicate
email/username, `422` on invalid input (username: 3-50 chars,
letters/digits/underscore only; password: 8+ chars).

`POST /api/auth/login` — `{email, password}` → `200` with
`{access_token, refresh_token, token_type: "bearer"}`. `401` for a wrong
password, unknown email, or deactivated user — deliberately identical in
all three cases so the response doesn't reveal which emails are
registered.

`POST /api/auth/refresh` — `{refresh_token}` → `200` with a **new**
access/refresh token pair (rotated, not just a new access token). `401`
if the token is expired, malformed, or is actually an access token.

`POST /api/auth/logout` — requires `Authorization: Bearer <access_token>`
→ `204`. Tokens are stateless JWTs (see
[`security.md`](security.md#passwords-and-tokens)); there is no
server-side session/blocklist table, so this doesn't revoke anything — it
just confirms the caller was authenticated. The client is expected to
discard its tokens; the access token also expires on its own shortly
after regardless.

`GET /api/auth/me` — requires `Authorization: Bearer <access_token>` →
`200` with the current user. `401` for a missing, malformed, expired, or
wrong-type token, or a token for a deactivated/deleted user.

Every endpoint below this point also requires
`Authorization: Bearer <access_token>` and enforces per-user ownership
server-side (see [`security.md`](security.md)).

### Files & Folders

```text
GET    /api/files
POST   /api/files/upload
GET    /api/files/{id}
GET    /api/files/{id}/download
PATCH  /api/files/{id}
DELETE /api/files/{id}

POST   /api/folders
GET    /api/folders/{id}
PATCH  /api/folders/{id}
DELETE /api/folders/{id}

GET    /api/search?q=...
```

`GET /api/files?folder_id=<uuid>` — a **directory listing**, not just a
flat file list: returns `{folder, subfolders, files}` for that folder
(omit `folder_id`, or leave it out entirely, for the root). `folder` is
`null` at the root. There is no separate `GET /api/folders` list
endpoint — this is how a client browses, including the root, in one
call. `404` if `folder_id` doesn't exist or isn't owned by the caller.

`POST /api/files/upload` — multipart form: `file` (required),
`folder_id` (optional, omit for root), `name` (optional — overrides the
uploaded file's own name). `201` with the file's metadata. `404` if
`folder_id` doesn't exist/isn't owned. `422` for an invalid name (empty,
too long, contains `/` or `\`, or is `.`/`..`) — the client-supplied name
is stored as metadata only and never used to build a filesystem path
(see [`security.md`](security.md#filesystem-safety)); the actual on-disk
key is server-generated.

`GET /api/files/{id}` — metadata only. `GET /api/files/{id}/download` —
streams the bytes with a `Content-Disposition` built from the stored
name. Both `404` for a missing/not-owned/deleted file.

`PATCH /api/files/{id}` / `PATCH /api/folders/{id}` — rename and/or move
in one call; only fields present in the request body are applied (so
`{"folder_id": null}` moves a file to the root, while omitting
`folder_id` entirely leaves it where it is). `404` if the target parent
doesn't exist/isn't owned. Moving a folder into itself or one of its own
subfolders is rejected with `409` (cycle prevention).

`DELETE /api/files/{id}` — **soft** delete (sets `deleted_at`); the file
disappears from listings, search, and direct access, but a proper
trash/restore flow (`GET /api/trash`, etc.) lands in Phase 6.
`DELETE /api/folders/{id}` — **hard** delete, and only succeeds on an
empty folder (`409` otherwise) — folders don't have `deleted_at` in the
schema, and cascading a delete would violate
[Rule 5](architecture.md#implementation-rules) ("never silently destroy
data").

`GET /api/search?q=...` — case-insensitive substring match over the
current user's folder and file names (deleted files excluded), up to 50
results each. `{folders: [...], files: [...]}`.

### Uploads — resumable chunked uploads

```text
POST   /api/uploads
GET    /api/uploads/{id}
POST   /api/uploads/{id}/chunks/{index}
POST   /api/uploads/{id}/complete
DELETE /api/uploads/{id}
```

For large files — the web UI switches to this automatically above 20MiB
(`CHUNKED_UPLOAD_THRESHOLD` in `web/src/api/uploads.ts`); small files
still just use `POST /api/files/upload`. See
[`storage.md`](storage.md#chunked-uploads) for how the C++ engine stores
and reconstructs chunks.

`POST /api/uploads` — `{file_name, file_size, chunk_size, folder_id?,
expected_hash?}` → `201` with the session (`id`, `total_chunks`, ...).
`file_size`/`chunk_size` must be positive; `total_chunks` is computed as
`ceil(file_size / chunk_size)`. `folder_id` isn't in
[`architecture.md`](architecture.md#database-design)'s original `uploads`
sketch — see `app/models/upload.py`'s docstring for why it's needed.
`expected_hash`, if given, is the client's claimed SHA-256 of the whole
file, verified on `/complete`; omit it to skip verification (the content
hash is still always computed from what was actually reconstructed).
`404` if `folder_id` doesn't exist/isn't owned, `422` for an invalid
`file_name` or a non-positive size.

`GET /api/uploads/{id}` — session status, plus `received_chunk_indices`
and `missing_chunk_indices` — this is how a resuming client (or the web
UI's "Resume upload" button) knows exactly what still needs to be sent,
without re-uploading anything that already arrived. `404` if not
found/not owned.

`POST /api/uploads/{id}/chunks/{index}` — multipart form: `chunk`
(required). `200` with `{index, received, received_count, total_chunks}`.
Resending an already-received index is safe (overwrites, doesn't
duplicate). `404` if the session isn't found/owned, `409` if the session
is no longer `pending` (completed, or past `expires_at`), `422` if
`index` is outside `[0, total_chunks)`, `502` if the engine can't store
the chunk.

`POST /api/uploads/{id}/complete` — verifies every chunk `0..total_chunks
- 1` is present, reconstructs the file (streamed, never buffered whole),
verifies it against `expected_hash` if one was given, stores it in the
content-addressable object store (same dedup as a regular upload), and
creates the `File` row. Returns `200` with the same shape as
`POST /api/files/upload`'s response (a `FileResponse`). `409` if
a chunk is missing or the hash doesn't match — nothing is stored in
either case, and the chunks that did arrive are left in place so the
client can fix the problem and call `/complete` again rather than
re-uploading everything.

`DELETE /api/uploads/{id}` — cancels an in-progress session: deletes its
temp chunks and the session row. Not in
[`architecture.md`](architecture.md#10-chunked-uploads)'s original
endpoint list, but the natural way for a client (or the cleanup sweep
below) to abandon an upload it no longer wants. `204` on success, `404`
if not found/owned.

**Abandoned/expired sessions:** `app/services/upload_service.sweep_expired_uploads`
deletes `pending` sessions past their `expires_at` (default 24h,
`settings.upload_session_expire_hours`) and their temp chunks. It isn't
wired to a scheduler — call it from a cron job, a management script, or
alongside `scripts/healthcheck.sh` once this runs somewhere that has one
(Rule 2: no infrastructure this project doesn't need yet).

## Planned (not yet implemented)

Endpoints below are listed for reference; they land with their
corresponding phase (see [`architecture.md`](architecture.md#development-phases)).

### Versions & Trash — Phase 6

```text
GET    /api/files/{id}/versions
POST   /api/files/{id}/versions/{version_id}/restore

GET    /api/trash
POST   /api/trash/{id}/restore
DELETE /api/trash/{id}
```

### Sharing

```text
POST   /api/shares
GET    /api/shares
DELETE /api/shares/{id}
GET    /s/{token}
```

## Internal: C++ engine API

Not part of the public API — reachable only from the backend, over the
Docker-internal network (see [`architecture.md`](architecture.md#19-c-engine-api)
and [`security.md`](security.md#the-engine-boundary)).

```text
GET  /health           implemented
POST /objects/exists   implemented
POST /objects/put      implemented
POST /objects/get      implemented
POST /objects/delete   implemented
POST /hash             implemented
POST /chunks/write     implemented
POST /chunks/finalize  implemented
POST /chunks/abandon   implemented
```

See [`storage.md`](storage.md#the-objectstore-interface) for the request/
response shapes of the implemented endpoints — they pass paths on the
storage volume shared between the backend and engine containers, not raw
bytes. `storage.md#chunked-uploads` covers the chunk endpoints
specifically.
