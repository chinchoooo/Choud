# Storage

> **Status:** object storage and deduplication (Phase 4), and chunked
> uploads (Phase 5), are both implemented — see `engine/src/storage/`,
> `engine/src/hashing/`, `engine/src/chunks/`, and
> `server/app/services/storage_service.py`/`upload_service.py`. See
> [`architecture.md`](architecture.md#development-phases).

Actual file bytes never touch PostgreSQL. They live on disk, owned
entirely by the C++ engine, and are addressed by content hash. See
[`architecture.md`](architecture.md#7-content-addressable-storage) for
the on-disk layout and [`architecture.md`](architecture.md#9-hashing) for
hashing requirements.

## The ObjectStore interface

API routes must never directly manipulate object-storage paths — all
access goes through a small interface the engine exposes over its local
HTTP API:

```cpp
class ObjectStore {
public:
    bool exists(const std::string& hash);

    void put(
        const std::string& hash,
        const std::filesystem::path& source
    );

    void get(
        const std::string& hash,
        const std::filesystem::path& destination
    );

    void remove(const std::string& hash);

    uint64_t size(const std::string& hash);
};
```

The exact interface may change during implementation; the principle
(`API routes must never directly manipulate object-storage paths`) does
not.

**As implemented:** `engine::storage::ObjectStore`
(`engine/include/storage/object_store.hpp`) matches this interface
closely — `exists`/`put`/`get`/`remove`/`size`, plus `path_for` for the
sharded on-disk layout. `engine::storage::StorageManager`
(`storage_manager.hpp`) is a thin facade over it that also exposes
`hash_file`, and is what the HTTP layer (`engine_server.cpp`) actually
calls. Since the backend and engine containers share the `storage_data`
Docker volume (see `docker-compose.yml`), the HTTP requests pass
*paths* on that shared volume, not raw bytes:

```text
POST /hash            {"path": "..."}                              -> {"hash": "..."}
POST /objects/exists  {"hash": "..."}                               -> {"exists": bool}
POST /objects/put     {"hash": "...", "source_path": "..."}         -> {"stored": true, "size": N}
POST /objects/get     {"hash": "...", "destination_path": "..."}    -> {"size": N}
POST /objects/delete  {"hash": "..."}                                -> {"deleted": bool}
```

`put` takes ownership of `source_path` (moves it into the store; falls
back to copy+remove across filesystems) — this is what makes
deduplication essentially free: putting the same hash twice is a no-op
that still consumes the caller's source file. `get` copies out to
`destination_path` and re-hashes the stored bytes first, raising a
`409`-mapped `ObjectCorruptedError` if they no longer match (Rule 5).

On the Python side, `server/app/services/file_service.py` never touches
these paths directly either — it writes uploaded bytes to a `staging/`
directory on the same shared volume, then calls
`app/services/storage_service.py` (which wraps `engine_client.py`) for
the hash and the put/get. Downloads are served from a throwaway staging
copy that a `BackgroundTask` deletes after the response is sent (see
`app/api/files.py`).

## Deduplication

Two files with the same content hash share one physical object. The
`files` table's `content_hash` column and `file_versions.content_hash`
are the reference-counting mechanism: an object is only a garbage
collection candidate once nothing references it.

Physical deletion happens in exactly one place: **permanently deleting a
file from the trash** (`app/services/trash_service.purge_file`). It removes
the file's rows first, then asks the engine (`/objects/delete`) to delete
each of its objects *only if no remaining `files` or `file_versions` row —
of any user — references that hash*. The engine's `remove_object` itself is
still unconditional; the reference check lives in Python, where the
references live. If the engine can't delete an object, the purge still
succeeds and the object is left as an unreferenced orphan (disk space is
leaked rather than data risked).

Two gaps remain until the garbage-collection work in Phase 15: orphans left
behind by failed deletes or failed uploads are never swept, and the
reference check is not atomic with a concurrent identical upload by someone
else (see the note in `trash_service.py`).

Track the distinction between **logical size** (what a user's quota sees)
and **physical size on disk** (deduplicated) — see
[`architecture.md`](architecture.md#storage-quota) once quotas land.

## Chunked uploads

See [`architecture.md`](architecture.md#10-chunked-uploads) for the HTTP
workflow and [`architecture.md`](architecture.md#11-chunk-storage) for
temporary chunk layout.

**As implemented:** `engine::chunks::ChunkStore`
(`engine/include/chunks/chunk_store.hpp`) is the chunk-storage analogue of
`ObjectStore` — chunks land at `${root}/uploads/<upload-id>/NNNNNN`
(six-digit zero-padded index), written with the same atomic
temp-file-then-rename pattern, and `upload_id` is validated (letters,
digits, hyphens only) before it's ever used to build a path, the same
defense-in-depth as hash validation. `engine::chunks::ChunkManager`
(`chunk_manager.hpp`) is the higher-level piece the HTTP layer calls:

1. `write()` stores one chunk (`POST /chunks/write` — `{upload_id, index,
   source_path}` → `{received: true}`; the engine takes ownership of
   `source_path`, same as `/objects/put`). Resending an index overwrites
   rather than duplicates.
2. `received_indices()` lists what's on disk for an upload — this is how
   `GET /api/uploads/{id}` on the Python side answers "what's still
   missing" without asking the engine on every status check (it mirrors
   the on-disk state into the `uploads.received_chunks` column instead —
   see `app/models/upload.py`).
3. `finalize()` (`POST /chunks/finalize` — `{upload_id, total_chunks,
   expected_hash?}` → `{hash, size}`) verifies chunks `0..total_chunks-1`
   are all present, **streams** them into a reconstructed file while
   hashing incrementally (never buffers the whole file — same bounded
   64KB buffer as `hashing::hash_file`), optionally verifies the result
   against `expected_hash`, hands it to `ObjectStore::put` (so dedup
   applies to chunked uploads too — two chunked uploads of identical
   content share one physical object, verified by
   `ChunkManagerTest.DuplicateContentAcrossUploadsIsDeduplicated`), then
   deletes `uploads/<upload-id>/`.
4. `abandon()` (`POST /chunks/abandon` — `{upload_id}` →
   `{removed: bool}`) deletes `uploads/<upload-id>/` without finalizing —
   used both for an explicit client cancel (`DELETE /api/uploads/{id}`)
   and by `app/services/upload_service.sweep_expired_uploads` for
   sessions past their `expires_at`.

A missing chunk or a hash mismatch on finalize both raise before anything
is written to `objects/` and leave the temp chunks exactly as they were —
the client can fix the problem (resend the missing chunk, or just
recheck what it claimed as `expected_hash`) and call `/complete` again,
rather than re-uploading everything from scratch. An interrupted upload
must never corrupt the object store: partial chunks stay in `uploads/`,
never in `objects/`, until finalize succeeds.

On the Python side, `app/services/upload_service.py` follows the same
staging pattern as `file_service.upload_file`: each chunk's bytes are
written to the shared `staging/` directory, then handed to the engine via
`storage_service.write_chunk`/`finalize_upload`/`abandon_upload` — never
touched directly. `POST /api/uploads/{id}/complete` builds the `File` row
from the engine's `finalize()` result exactly like a regular upload does,
so a chunked upload and a plain `POST /api/files/upload` produce
identical rows (`docs/api.md#uploads--resumable-chunked-uploads`).

On the web client, `web/src/api/uploads.ts` is a plain fetch chain (no
upload library): create a session, slice the `File` with `File.slice()`,
POST each missing chunk (with a small per-chunk retry), then complete.
`resumeUpload()` always re-reads `GET /api/uploads/{id}` first and only
(re)sends what the server says is still missing — that's the whole
"resume after an interrupted connection" story, and it's the same
function used both for automatic retry and for the UI's manual "Resume
upload" button.

## Testing

Per [`architecture.md`](architecture.md#implementation-rules) (Rule 6),
the engine test suite (`engine/tests/`) must cover the failure cases, not
just the happy path:

- `hashing_tests.cpp` — known SHA-256 test vectors; streaming a file
  larger than the read buffer produces the same hash as reading it whole.
- `storage_tests.cpp` — put/get/exists/remove round-trip; a `get` for a
  missing hash fails cleanly; a corrupted object on disk is detected
  rather than silently returned.
- `chunk_tests.cpp` — resuming after a subset of chunks were received;
  finalize rejects a missing chunk; an abandoned upload is cleaned up
  without touching `objects/`.
