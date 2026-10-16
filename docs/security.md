# Security

## Current status

Phase 1 has no authentication yet — `/api/health` is the only endpoint,
and it exposes no user data. The rules below govern every phase from here
on; they're documented now so later phases are held to them from the
start.

## Passwords and tokens

- Passwords are hashed with **Argon2id** (`argon2-cffi`). Plaintext
  passwords are never stored, logged, or returned by the API.
- JWT access tokens (`PyJWT`) are short-lived (see
  `ACCESS_TOKEN_EXPIRE_MINUTES` in [`.env.example`](../.env.example)).
  Signing secrets live only in environment variables — never in git.
- Share tokens (Phase "Sharing") are cryptographically random and stored
  as a hash, never as the raw token — the raw token exists only in the
  share URL itself. Database IDs are never used as share credentials.

## Authorization

Every resource operation verifies ownership server-side. A user must
never be able to reach another user's files, folders, uploads, versions,
or shares — enforced in the API layer, not the frontend. Frontend checks
are UX, not security.

## Filesystem safety

- Filenames are validated before touching the filesystem.
- Storage paths are always derived from a validated content hash or
  server-generated ID — **never** built directly from a client-supplied
  filename or path:

  ```python
  # never do this
  path = STORAGE_ROOT / user_supplied_filename
  ```

  Path traversal (`../../etc/passwd`-style input) is a rejected request,
  not a validated one.
- Internal filesystem paths are never exposed in API responses or error
  messages.
- Upload endpoints validate chunk metadata and upload ownership before
  writing anything to disk.

## The engine boundary

The C++ engine (see [`architecture.md`](architecture.md#19-c-engine-api))
listens only on `localhost` or the Docker-internal network — it is never
reachable from outside the container network, and Docker Compose does
not publish its port to the host (see `docker-compose.yml`). All
authentication and authorization happen in the Python API before a
request ever reaches the engine; the engine itself trusts its caller.

## Encryption

No custom cryptography, ever — established libraries only
(`argon2-cffi`, `PyJWT`, OpenSSL/libsodium once the engine needs
primitives). For the current phases:

- HTTPS protects data in transit (Caddy, see [`deployment.md`](deployment.md)).
- Disk encryption is left to the operating system.
- Application-level end-to-end encryption is an explicit future phase,
  not part of the MVP — see
  [`architecture.md`](architecture.md#explicit-non-goals).

## Logging

Structured logging (`app/core/logging.py`) records authentication
failures, upload/download start/completion/failure, storage failures,
synchronization failures, and unexpected exceptions.

**Never logged:** passwords, access tokens, private share tokens, raw
file contents.

## Previews, thumbnails and upload limits (Milestone 2)

- **Media tokens.** `<img>`, `<video>` and in-app players cannot send an `Authorization` header,
  so previews use a separate JWT type (`media`, one hour) in the URL path. It opens only
  `/api/media/.../content` and `.../thumbnail`, only for the owner's own files; it is rejected by
  every other route, and an access token is rejected by the media routes. It appears in URLs, so
  it can show up in proxy logs and browser history: that is why it is read-only and short-lived.
- **Uploaded files never run in the app's origin.** Only an allowlist of media types
  (png/jpeg/gif/webp/avif/bmp, pdf, plain text, common video and audio) is sent inline. HTML, SVG,
  XML and anything else is sent as an opaque `attachment` with `X-Content-Type-Options: nosniff`
  and `Content-Security-Policy: default-src 'none'; sandbox`. The web and Android viewers show
  text and HTML as escaped text, and never render SVG.
- **Thumbnails.** Images are decoded with a pixel ceiling and, for JPEG, a down-sampling decode.
  Video thumbnails run a pinned static `ffmpeg` only on files whose first bytes prove they are
  MP4/MOV or WebM/MKV, with the demuxer forced and `-protocol_whitelist file`, so an uploaded
  playlist or concat script cannot make the server read other files or fetch URLs.
- **Upload limits.** Each chunk must be exactly the promised size (so the quota check at session
  creation cannot be bypassed with a bigger chunk), chunks and chunk counts are bounded, and the
  single-request upload is read in blocks and refused past 128 MiB. Caddy additionally caps
  request bodies (160 MB for uploads, 10 MB for everything else).
- **Not independently penetration-tested yet.** A red-team agent run was started but stopped by a
  safety check before it did anything. The checks above are covered by tests, but an independent
  attack pass is still worth doing before the server is exposed beyond a tailnet.

## Hardening (Phase 10)

Rate limiting, security headers, and failure-recovery monitoring land in
Phase 10 — see [`architecture.md`](architecture.md#development-phases).
