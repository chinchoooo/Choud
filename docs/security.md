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

## The Vault (client-side encryption)

The Vault page keeps files that **even the server cannot read**. It is implemented entirely in the
web app (`web/src/vault/`) with the browser's Web Crypto API; the backend needs no special support and
only ever stores ordinary files whose contents happen to be ciphertext.

- **Key:** PBKDF2-SHA256, 600,000 iterations, random 16-byte salt, from a passphrase that never leaves
  the browser, giving an AES-256-GCM key. The key lives only in memory: dropped on "Lock now", after
  10 idle minutes, and when leaving the page.
- **Data:** split into 1 MiB chunks, each sealed with AES-GCM under its own IV (8-byte random per-file
  nonce + chunk counter); the chunk number and a last-chunk flag are authenticated, so reordering,
  dropping or truncating chunks is detected, not just flipped bits.
- **Names:** the real name, type, size and date of every file live only inside an encrypted index
  (`manifest.cvault`); the server sees `<random-id>.cvault` files. Index updates are new *versions*, so
  the index itself has history.
- **What the server still sees:** that a folder named "Vault (encrypted)" exists, how many sealed files
  it holds, their sizes and when they were added. No previews, thumbnails or search work on vault
  files, by design.
- **A wrong passphrase is recognised** by decrypting a sealed check value; weak or unknown settings in
  the config are refused rather than trusted.
- **No recovery.** Forget the passphrase and the data is gone. The create form makes you confirm that.
- **Limits:** files are sealed in browser memory, so a single file is limited to 400 MB. The Vault
  protects against a curious or compromised server and stolen backups; it cannot protect against
  malware on the device you unlock it from, or a malicious copy of the web app served to you (the
  page's own code does the encryption).

## Browser security headers and encrypted backups

- **Headers.** The web image (nginx) sends a strict Content-Security-Policy (scripts only from the
  app itself, no framing by others, connections only to its own origin), `nosniff`, `no-referrer`,
  `X-Frame-Options: DENY`, a restrictive Permissions-Policy and `Cross-Origin-Opener-Policy`. Caddy
  adds the same baseline to everything the backend answers *only where the backend did not set its
  own* (previews and public share pages keep their stricter policies) and hides the server banner.
  The CSP keeps `'unsafe-inline'` for **styles** only (React sizes elements with style attributes).
- **Encrypted backups.** Set `BACKUP_PASSPHRASE_FILE` and `scripts/backup.sh` encrypts the database
  dump, the object store and your `.env` secrets as they are written (AES-256-CBC, PBKDF2-SHA256 with
  600,000 iterations, random salt): no plain copy ever lands in the backup folder, and the script
  refuses to continue if the passphrase file is missing. `restore.sh` proves the passphrase works and
  the dump is whole **before** it stops anything. This is encryption at rest, not a signature: the
  checksums catch accidental damage but someone who can rewrite the backup could rewrite them too.
  **Keep a copy of the passphrase off the machine; without it the backups cannot be read.** Without
  the setting, backups are plain and the script warns that they contain your secrets.

## Rewind, pruning, drop links and the sign-in history

- **Rewind never destroys.** A restore appends a new version, leaves files created after the chosen
  time alone, and tree restores preview first. Rewinding is bounded by what history exists: pruned
  versions and purged files cannot be recovered.
- **Pruning is explicit.** It previews by default, always keeps each file's current version, and
  deletes an object from disk only if no file or version of any user still references it.
- **Drop (file-request) links** expose no listing, no download and no preview: the only action is
  adding files, with the same size/quota/rate limits as edit links, and a drop never overwrites.
- **Download limits** make a link inactive for everyone (the same uniform 404) once used up.
- **Sign-in history** records attempts against real accounts only (a made-up email leaves no trace),
  keeps the address and client string for a year, is visible only to the account owner, and flags a
  success from an unseen address and client. The administrator view (`/api/admin/server`) is
  restricted to the oldest account.

## Search indexing (Phase 14)

- Text is read from files in the background. Plain-text types are read in-process (first 5 MB, binary
  files skipped); **PDFs and Office/OpenDocument files are parsed in a separate subprocess** with a
  60-second timeout and (on Linux) a 1 GiB memory and CPU limit, because anyone holding an edit link
  can upload such files. A file that cannot be parsed is recorded as failed and not retried.
- Zip parts larger than 30 MB uncompressed are ignored (zip-bomb guard); at most 1,000,000 characters
  are kept per file.
- The index is derived data: results are only served when the stored text matches the file's current
  content hash, and it is deleted with the file. Queries are parameterised and `%` / `_` match literally.

## Two-factor login (Phase 13)

- Optional per account: standard TOTP (RFC 6238, SHA-1, 6 digits, 30 s) with HMAC from the standard
  library, checked against the RFC test vectors. Any authenticator app works.
- It is only required at **login**. After that, the app/desktop client/phone keep working with their
  refresh tokens, so a background backup is never interrupted by a code prompt.
- A code works once (the last used 30-second step is remembered), the previous and next window are
  accepted for clock drift, and five wrong codes lock code entry for that account for 15 minutes.
- Ten single-use recovery codes are made when it is turned on (stored only as SHA-256 hashes, shown
  once). Turning it off needs the password **and** a current code.
- The TOTP secret is stored in the database as base32 text. Someone who can read the database can
  read it, but they could already read everything else the database protects.
- Passkeys are not built.

## Who can register

`REGISTRATION_MODE` is `invite` by default: the first account on an empty server is free, every
later one needs a single-use, expiring code made by the administrator (the oldest account).
`open` allows anyone who can reach the server; `closed` allows nobody; an unknown value behaves
like `invite`. Existing servers pick up `invite` on the next deploy, so strangers cannot sign up.

## Public share links (Phase 12)

- **Bearer links.** `/s/<token>` is 256 bits of randomness; whoever holds it can see what it points
  at. The token is stored as-is (not hashed) so the owner can copy the link again; revoking the row
  kills it at once. Optional expiry and an Argon2id-hashed password add locks.
- **A link reaches only its target.** Every file or folder request is checked against the share:
  the shared file itself, or for a folder link, an item whose parent chain reaches the shared
  folder. Other users' items, siblings and the account root are unreachable even by guessing ids.
- **Uniform failure.** Unknown, expired, revoked and trashed-target links return the same 404.
- **Unlocking.** A correct password sets an HMAC-signed, HttpOnly, SameSite=Lax cookie scoped to that
  one link for one hour; changing the password invalidates every earlier unlock. Password attempts
  are limited to 10 per minute per IP.
- **No script, ever.** The pages are server-rendered, every name is HTML-escaped, and they are sent
  with `default-src 'none'` (no scripts at all), `nosniff`, `no-referrer`, `no-store`, and
  `frame-ancestors 'none'`. Files are only previewed inline for the same media allowlist as the
  media routes; HTML/SVG and everything else is an attachment.

### Edit links

- A link made with `permission: edit` lets whoever holds it add files, make folders, rename and
  trash files inside the shared folder (or upload new versions of one shared file). It is as
  powerful as the secrecy of the link: use an expiry and a password, and revoke when done.
- Nothing an editor does is unrecoverable: deletes go to the owner's trash, same-name uploads are
  new versions, there is no hard delete and no move out of the shared folder.
- Every action re-checks that its target is inside the link; uploads count against the **owner's**
  quota and obey the normal size limits (128 MiB per file, 20 files per request); edit actions are
  rate limited (60 per minute per IP).

## Hardening (Phase 10)

Rate limiting, security headers, and failure-recovery monitoring land in
Phase 10 — see [`architecture.md`](architecture.md#development-phases).
