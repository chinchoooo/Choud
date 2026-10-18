"""A local, in-process stand-in for the real C++ engine, used only in tests.

Implements the storage_service-facing surface (hash_file/exists/put/get/
delete) with Python's hashlib and the filesystem directly, so the test
suite doesn't need a running engine process — mirroring how the DB layer
runs against SQLite instead of a real PostgreSQL server (see
`app/core/types.GUID`). It mimics the real `ObjectStore`'s on-disk layout
(two-character hash-prefix sharding) and behavior (idempotent put,
not-found/corrupted detection on get) closely enough that dedup and
integrity tests exercise real behavior, not just a mock's say-so.
"""

import hashlib
import shutil
from pathlib import Path

from app.services.engine_client import ObjectCorruptedError, ObjectNotFoundError


class FakeEngineClient:
    def __init__(self, root: Path) -> None:
        self._objects_dir = Path(root) / "objects"
        self._objects_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, content_hash: str) -> Path:
        return self._objects_dir / content_hash[:2] / content_hash

    def local_object_path(self, content_hash: str):
        path = self._path_for(content_hash)
        return path if path.is_file() else None

    def hash_file(self, path: str) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def exists(self, content_hash: str) -> bool:
        return self._path_for(content_hash).is_file()

    def put(self, content_hash: str, source_path: str) -> int:
        target = self._path_for(content_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.move(source_path, target)
        else:
            Path(source_path).unlink(missing_ok=True)
        return target.stat().st_size

    def get(self, content_hash: str, destination_path: str) -> int:
        source = self._path_for(content_hash)
        if not source.is_file():
            raise ObjectNotFoundError(f"no object stored for hash: {content_hash}")
        if self.hash_file(str(source)) != content_hash:
            raise ObjectCorruptedError(f"stored object does not match its hash: {content_hash}")
        Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination_path)
        return source.stat().st_size

    def delete(self, content_hash: str) -> bool:
        target = self._path_for(content_hash)
        existed = target.is_file()
        target.unlink(missing_ok=True)
        return existed

    def check_health(self) -> bool:
        return True

    # --- chunked uploads (Phase 5) ---------------------------------------
    #
    # Mirrors engine::chunks::ChunkStore/ChunkManager: chunks land at
    # <root>/uploads/<upload_id>/NNNNNN, finalize verifies every expected
    # index is present, reconstructs, hashes, and stores via the same
    # `put`-shaped path as a normal object, then removes the temp
    # directory. A missing chunk or a hash mismatch both raise
    # ObjectCorruptedError, matching the real engine's 409-for-both
    # behavior (see engine_server.cpp's /chunks/finalize handler).

    def _upload_dir(self, upload_id: str) -> Path:
        return self._objects_dir.parent / "uploads" / upload_id

    def write_chunk(self, upload_id: str, index: int, source_path: str) -> None:
        target = self._upload_dir(upload_id) / f"{index:06d}"
        target.parent.mkdir(parents=True, exist_ok=True)
        Path(source_path).replace(target)

    def finalize_chunks(
        self, upload_id: str, total_chunks: int, expected_hash: str | None = None
    ) -> tuple[str, int]:
        upload_dir = self._upload_dir(upload_id)
        for i in range(total_chunks):
            if not (upload_dir / f"{i:06d}").is_file():
                raise ObjectCorruptedError(f"missing chunk {i} for upload {upload_id}")

        hasher = hashlib.sha256()
        reconstructed = upload_dir / "reconstructed.tmp"
        with open(reconstructed, "wb") as out:
            for i in range(total_chunks):
                data = (upload_dir / f"{i:06d}").read_bytes()
                hasher.update(data)
                out.write(data)
        computed_hash = hasher.hexdigest()

        if expected_hash is not None and expected_hash != computed_hash:
            reconstructed.unlink(missing_ok=True)
            raise ObjectCorruptedError(
                f"reconstructed content does not match expected hash for upload {upload_id}"
            )

        size = self.put(computed_hash, str(reconstructed))
        self.abandon_chunks(upload_id)
        return computed_hash, size

    def abandon_chunks(self, upload_id: str) -> bool:
        upload_dir = self._upload_dir(upload_id)
        existed = upload_dir.is_dir()
        shutil.rmtree(upload_dir, ignore_errors=True)
        return existed
