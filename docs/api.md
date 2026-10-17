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

Two-factor login (authenticator app): `GET /api/auth/2fa` (status), `POST /api/auth/2fa/setup` (returns `secret` + `otpauth_uri` for a QR code), `POST /api/auth/2fa/enable` `{code}` (returns 10 one-time `recovery_codes`, shown once), `POST /api/auth/2fa/disable` `{password, code}`, `POST /api/auth/2fa/recovery-codes` `{code}` (replaces the old codes). When it is on, `POST /api/auth/login` answers `401 {"detail": "two_factor_required"}` until the request also carries `otp` (an app code or a recovery code). Refresh tokens are unaffected.

`GET /api/auth/registration` — `{mode, open, invite_required, first_account}` for the sign-up page.

Invites (administrator = the oldest account): `POST /api/invites` `{note?, expires_in_hours?, storage_quota_bytes?}` returns a single-use `code`; `GET /api/invites`; `DELETE /api/invites/{id}`. A code is passed as `invite_code` to register and may carry its own storage quota.

`POST /api/auth/register` — `{username, email, password, invite_code?}` → `201` with the
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

**Same name = new version.** If the caller already has a live (non-trashed)
file with that name in that folder, the upload does not create a second
file: it appends a new [version](#versions) and returns the *existing*
file's metadata (same `id`, new `content_hash`/`size`), still `201`.
Uploading **identical bytes** under the same name is a no-op that returns
the file unchanged. The same rule applies when a chunked upload completes.

**Conditional writes (`base_version_id`).** Sync clients must not overwrite an
edit they have never seen. The upload form accepts an optional
`base_version_id`: the id of the version the client started from (as reported
by the snapshot or a previous upload), or the literal `none` meaning "nothing
should exist at this path yet". If the precondition no longer holds nothing is
written and the response is `409`:

```json
{"detail": {"code": "version_conflict", "message": "...",
            "file_id": "<uuid or null>", "current_version_id": "<uuid or null>"}}
```

Identical content is never a conflict, and a `base_version_id` for a file that
has since been deleted simply creates a new file (the caller's data is never
dropped). `POST /api/uploads` takes the same `base_version_id` in its JSON
body and applies it on `/complete`; a conflict there marks the session
`aborted` because its chunks were already consumed. `DELETE
/api/files/{id}?base_version_id=<uuid>` moves a file to the trash only if it is
still on that version. A malformed value is `422`.

`GET /api/files/{id}` — metadata only. `GET /api/files/{id}/download` —
streams the bytes with a `Content-Disposition` built from the stored
name. Both `404` for a missing/not-owned/deleted file.

`PATCH /api/files/{id}` / `PATCH /api/folders/{id}` — rename and/or move
in one call; only fields present in the request body are applied (so
`{"folder_id": null}` moves a file to the root, while omitting
`folder_id` entirely leaves it where it is). `404` if the target parent
doesn't exist/isn't owned. Moving a folder into itself or one of its own
subfolders is rejected with `409` (cycle prevention). Renaming or moving a
**file** onto a name that already exists in the destination folder is also
`409` — a file's identity for versioning is (owner, folder, name).

`DELETE /api/files/{id}` — **soft** delete (sets `deleted_at`); the file
disappears from listings, search, and direct access and shows up in the
[trash](#trash), where it can be restored or permanently deleted.
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

### Versions

```text
GET    /api/files/{id}/versions
GET    /api/files/{id}/versions/{version_id}/download
POST   /api/files/{id}/versions/{version_id}/restore
```

`GET .../versions` → `{file_id, versions: [...]}`, **newest first**. Each
version: `id`, `file_id`, `version_number` (1-based, strictly increasing),
`content_hash`, `size`, `restored_from_version` (the number it copied, or
`null`), `created_by`, `created_at`, `is_current`.

`GET .../versions/{version_id}/download` streams that version's bytes under
the file's current name. A missing/corrupted object is a clean `500`.

`POST .../versions/{version_id}/restore` makes an old version's content
current by **appending a new version** (`201`, returns the new version).
History is never rewritten, so the version you restored *from* stays
listed and downloadable. Restoring the version that is already current is
`409`. All three endpoints `404` for a file that is missing, not owned by
the caller, or in the trash, and for a `version_id` that belongs to a
different file.

### Trash

```text
GET    /api/trash
POST   /api/trash/{id}/restore
DELETE /api/trash/{id}
```

`DELETE /api/files/{id}` moves a file into the trash (soft delete); these
endpoints manage it from there. Trash holds **files only** and never
expires on its own.

`GET /api/trash` → `{files: [...]}`, most recently deleted first; each item
has `id`, `name`, `folder_id`, `mime_type`, `size`, `content_hash`,
`deleted_at`.

`POST /api/trash/{id}/restore` → `200` with the file's metadata. It returns
to its original folder; if that folder has since been deleted it goes to the
root, and if a live file already has its name there it is renamed
`name (restored).ext` (then `(restored 2)`, `(restored 3)`, ...). Nothing is
ever overwritten. Version history comes back with it.

`DELETE /api/trash/{id}` → `204`. **Permanent.** Removes the file and all
its versions, then deletes each stored object only if no other file or
version — of *any* user, since identical bytes are shared — still references
that content hash. If the engine can't delete an object, the request still
succeeds and the object is left as an unreferenced orphan for a future
garbage-collection pass.

All three `404` for a file that isn't in the caller's trash (unknown, live,
or someone else's). A live file must be deleted before it can be purged.

### Sync

```text
GET  /api/sync/snapshot
POST /api/sync/folders
```

Used by the desktop client (and later the phone client); they need the whole
tree by *path*, not a folder-by-folder walk.

`GET /api/sync/snapshot` → `{generated_at, folders: [...], files: [...]}`. Each
folder has `id`, `parent_id`, `path`; each file has `id`, `folder_id`, `name`,
`path`, `size`, `content_hash`, `version_id`, `updated_at`. Paths are
`/`-separated, relative to the root, with no leading slash. **Trashed files are
absent** — to a sync client a file in the trash is a deleted file (it stays
recoverable on the server). `version_id` is what the client remembers after a
sync and sends back as `base_version_id`. A file and a folder may share a name
in the same parent on the server; a local filesystem cannot hold both, so
clients must detect that collision and skip the entry.

**Cheap polling (`ETag`).** The snapshot response carries an `ETag` derived from
its content (ids, paths, versions, hashes - not timestamps), so it changes
exactly when the tree does: an upload, edit, rename, move, delete, restore or new
folder. Send it back as `If-None-Match` and an unchanged tree is answered with a
bodyless `304 Not Modified` (weak validators, comma lists and `*` are accepted).
Polling every 30 s therefore costs almost nothing, which is what makes it
practical on a phone's mobile data. The ETag is per user.

`POST /api/sync/folders` with `{"path": "Research/2026"}` creates any missing
folders and returns `{id, path}` of the leaf (`{id: null, path: ""}` for the
root). Idempotent; reuses existing folders; leading/trailing slashes are
ignored. Components with `..`, `.`, backslashes, null bytes, over 255
characters, or more than 64 levels are `422` and nothing is created.

### Library, previews and thumbnails (Milestone 2)

All owner-scoped, all under the normal bearer token unless noted.

| Endpoint | What it does |
| --- | --- |
| `GET /api/library/photos?kind=all\|image\|video&offset=&limit=` | Every photo/video from every folder, newest first by `taken_at` (else upload time). `{items, total, offset, limit}` |
| `GET /api/library/recent?limit=` | Most recently added or changed files |
| `GET /api/library/favorites` | Starred files |
| `PUT /api/library/favorites/{file_id}` / `DELETE ...` | Star / unstar (idempotent, `204`) |
| `GET /api/library/usage` | `{used_bytes, quota_bytes, file_count}`; counts every version, so it only ever over-estimates |
| `GET /api/library/activity?limit=` | What happened to your files: uploaded, new_version, renamed, moved, trashed, restored, purged |
| `POST /api/media/token` | A **media token** (read-only, 1 hour) for `<img>`/`<video>`/players, which cannot send a header |
| `GET /api/media/{token}/{file_id}/content` | The bytes, inline, with `Range` support so video seeks. Only an allowlist of media types is served inline (see `docs/security.md`) |
| `GET /api/media/{token}/{file_id}/thumbnail?size=128\|256\|512\|1024` | JPEG thumbnail of an image or video, generated once and cached by content hash |

File responses (`GET /api/files`, search, library routes) also carry `taken_at`, `modified_at`,
`is_favorite` and `folder_path`. `modified_at` is the uploading device's own last-modified time
and is what clients show as a file's date; `created_at`/`updated_at` stay the server's times.
`PATCH /api/files/{id}` accepts `modified_at` and `taken_at` (and `null` to clear) so a client can
fix the dates of files it uploaded before the server recorded them. Uploads (`POST /api/files/upload` and `POST /api/uploads`) accept an optional
`taken_at` (ISO 8601) so a backed-up photo sorts by when it was taken, not when it was uploaded.

Limits: a single-request upload is at most 128 MiB (`413` beyond that; use the chunked upload),
a chunk is at most 64 MiB and **must be exactly the size the session promised**, a session has at
most 20,000 chunks, and an upload that would exceed the user's quota is a `413`.

### Rewind (browse and restore the past)

`GET /api/rewind/browse?at=<ISO time>&folder_id=` shows a folder as it was at that time: its folders
that already existed and its files with the content they had then, each flagged `changed` (today's
content differs) and `trashed` (in the trash today). `POST /api/rewind/restore-file`
`{file_id, at}` puts one file back. `POST /api/rewind/restore-tree` `{folder_id?, at, dry_run}`
previews (the default) or performs putting a whole folder tree, or everything, back. A restore adds a
**new version** (the version you rewound away from stays in history), takes files out of the trash,
and **never touches files created after that time**. Times in the future are refused. Names and
locations are the current ones (renames/moves are not recorded) and purged files cannot return.

### Space insights

`GET /api/insights/space` returns `logical_bytes` (every version counted in full), `stored_bytes`
(identical content once), `dedup_saved_bytes`, `current_bytes`, `trash_bytes`, `history_bytes` (only
held by old versions), `by_type`, the `biggest` files and groups of `duplicates` (same content under
different names). `POST /api/insights/prune-versions` `{keep, dry_run}` deletes all but the newest
`keep` versions of each file (the current one always stays; objects are removed from disk only if
nothing else uses them). It previews unless `dry_run` is `false`, and pruned versions cannot be
restored or rewound to.

### Memories, sign-in history and the server view

`GET /api/library/memories`: photos and videos from this day in earlier years, grouped by year.
`GET /api/auth/security-log`: your recent sign-in attempts (time, address, client, success, and
`new_device` for a success from an unseen address + client). `GET /api/admin/server`
(administrator only): disk free/total, users, files, versions, logical vs stored bytes, uploads in
progress, search-index backlog and failures, registration mode.

### File requests and one-time links

`POST /api/shares` also accepts `permission: "drop"` (folders only) and `max_downloads`. A **drop**
link is a file request: the visitor page only has an upload form, shows nothing that is already in the
folder, cannot download, preview, rename or delete, and never overwrites (a clashing name becomes
`name (2).ext`). `max_downloads` makes the link stop working for everyone once that many downloads
have happened (1 = a one-time link); it can be raised, removed or changed with `PATCH`.

### Search inside files (Phase 14)

`GET /api/search?q=...` returns `{folders, files, content}`. `folders` and `files` are name matches
(substring, case-insensitive). `content` lists other files whose **text** matches, each as
`{file, snippet}` with the passage that matched. Text is extracted in the background (plain text and
code, PDF, .docx/.pptx/.odt/.ods) a few files at a time, so a new upload becomes searchable within
about a minute. On PostgreSQL the match is whole-word and ranked; trashed files and other
people's files are never returned. `python -m app.cli index [--all]` indexes everything now or
rebuilds from scratch (`INDEX_INTERVAL_SECONDS=0` turns the background pass off).

### Sharing: public links (Phase 12)

| Endpoint | What it does |
| --- | --- |
| `POST /api/shares` | Make a link to **one** file (`file_id`) or folder (`folder_id`). Optional `expires_in_hours` (1-8760), `password` (4+ chars), `label`, `permission` (`view` default, or `edit`). Returns the share with `token` and `url_path` (`/s/<token>`; add your own origin) |
| `GET /api/shares` | Your active links, with `download_count`, `last_accessed_at`, `has_password`, `expires_at` |
| `PATCH /api/shares/{id}` | Change `label`, `password` (`null` removes it), `expires_in_hours` (`null` = never), `permission` |
| `DELETE /api/shares/{id}` | Revoke: the link stops working immediately (`204`) |

The visitor side needs no account, and is served as plain HTML (no scripts) by the backend:

| URL | What it does |
| --- | --- |
| `GET /s/{token}` | A file link shows the file with a download button (and an inline preview for images, video and audio). A folder link lists the folder; `?folder=<id>` navigates inside it |
| `POST /s/{token}/unlock` | Form post of `password`; sets a one-hour signed cookie for that link only (rate limited: 10 per minute per IP) |
| `GET /s/{token}/file/{file_id}` | The bytes as an attachment (`?inline=1` only for safe media types) |
| `GET /s/{token}/file/{file_id}/open` | A preview page for a file inside a shared folder |
| `GET /s/{token}/file/{file_id}/thumbnail` | A small thumbnail for images and videos |
| `POST /s/{token}/upload` | **Edit links only.** Form upload of up to 20 `files` (+ `folder`, empty = the shared folder). A same-name file becomes a new version. On a file link: exactly one file, stored as a new version of the shared file |
| `POST /s/{token}/mkdir` | Edit folder links: `name`, `parent` |
| `POST /s/{token}/rename` | Edit folder links: `file_id`, `name` |
| `POST /s/{token}/trash` | Edit folder links: `file_id`; moves the file to the **owner's trash** (never a hard delete) |

On a view-only link all four return `403`. Targets outside the shared folder return the uniform `404`.
Refusals (name taken, too large, over quota) render a small page with a Back button.
There is deliberately no per-user sharing: a link is the only way to share.

A link only reaches what it was made for: a file link that one file, a folder link only files and
folders at or below that folder. Unknown, expired, revoked and trashed-target links all give the same
404 page. Sharing is recorded in the activity log.

## Planned (not yet implemented)

Endpoints below are listed for reference; they land with their
corresponding phase (see [`architecture.md`](architecture.md#development-phases)).

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
