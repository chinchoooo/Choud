"""Wraps EngineClient object-storage calls (put/get/exists/remove).

`file_service` calls this instead of touching the filesystem directly —
API routes (and the services above them) must never directly manipulate
object-storage paths (docs/storage.md#the-objectstore-interface); all
access goes through the engine's local HTTP API.
"""

from pathlib import Path

from app.services.engine_client import EngineClient, get_engine_client


class StorageService:
    def __init__(self, client: EngineClient | None = None) -> None:
        self._client = client or get_engine_client()

    def hash_file(self, path: Path) -> str:
        return self._client.hash_file(str(path))

    def local_path(self, content_hash: str) -> Path | None:
        """The object's file on the shared volume, for read-only use (None if unavailable)."""
        finder = getattr(self._client, "local_object_path", None)
        return finder(content_hash) if finder else None

    def exists(self, content_hash: str) -> bool:
        return self._client.exists(content_hash)

    def store(self, content_hash: str, source: Path, verified: bool = False) -> int:
        """Stores `source`'s bytes under `content_hash`. Returns the size in bytes.

        Consumes `source` — see `EngineClient.put`.
        """
        return self._client.put(content_hash, str(source), verified=verified)

    def retrieve(self, content_hash: str, destination: Path) -> int:
        return self._client.get(content_hash, str(destination))

    def remove(self, content_hash: str) -> bool:
        return self._client.delete(content_hash)

    # --- chunked uploads (Phase 5) ---------------------------------------

    def write_chunk(self, upload_id: str, index: int, source: Path) -> None:
        """Stores `source`'s bytes as chunk `index` of `upload_id`. Consumes `source`."""
        self._client.write_chunk(upload_id, index, str(source))

    def finalize_upload(
        self, upload_id: str, total_chunks: int, expected_hash: str | None = None
    ) -> tuple[str, int]:
        """Reconstructs `upload_id`'s chunks into a stored object. Returns `(hash, size)`."""
        return self._client.finalize_chunks(upload_id, total_chunks, expected_hash)

    def abandon_upload(self, upload_id: str) -> bool:
        return self._client.abandon_chunks(upload_id)


def get_storage_service() -> StorageService:
    return StorageService()
