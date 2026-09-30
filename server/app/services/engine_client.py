import httpx

from app.core.config import get_settings

settings = get_settings()


class EngineError(Exception):
    """Base class for all storage-engine failures."""


class EngineUnavailableError(EngineError):
    """The engine could not be reached at all (network/connection failure)."""


class ObjectNotFoundError(EngineError):
    """No object is stored under the requested hash."""


class ObjectCorruptedError(EngineError):
    """The stored object's bytes no longer match its hash."""


class InvalidRequestError(EngineError):
    """The engine rejected the request as malformed (bad hash, missing field, ...)."""


def _error_detail(response: httpx.Response) -> str:
    try:
        return response.json().get("error", response.text)
    except ValueError:
        return response.text


class EngineClient:
    """Thin HTTP client for the local C++ storage engine.

    Only the operations the API actually needs are exposed here (Rule 4:
    keep the C++ API small). Object storage, hashing and chunk endpoints
    are added as the corresponding phases land.
    """

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self._base_url = base_url or settings.engine_base_url
        self._timeout = timeout or settings.engine_timeout_seconds

    def check_health(self) -> bool:
        try:
            response = httpx.get(f"{self._base_url}/health", timeout=self._timeout)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = httpx.post(f"{self._base_url}{path}", json=payload, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise EngineUnavailableError(f"could not reach the storage engine: {exc}") from exc

        if response.status_code == 404:
            raise ObjectNotFoundError(_error_detail(response))
        if response.status_code == 409:
            raise ObjectCorruptedError(_error_detail(response))
        if response.status_code == 400:
            raise InvalidRequestError(_error_detail(response))
        if response.status_code >= 500:
            raise EngineError(_error_detail(response))
        response.raise_for_status()
        return response.json()

    def hash_file(self, path: str) -> str:
        """Streaming SHA-256 of a file already on the shared storage volume."""
        return self._post("/hash", {"path": path})["hash"]

    def exists(self, content_hash: str) -> bool:
        return self._post("/objects/exists", {"hash": content_hash})["exists"]

    def put(self, content_hash: str, source_path: str) -> int:
        """Stores `source_path`'s bytes under `content_hash`. Returns the size in bytes.

        The engine takes ownership of `source_path` (moves it into the
        store) — treat it as consumed after this call, whether or not an
        object already existed under that hash (deduplication).
        """
        body = self._post("/objects/put", {"hash": content_hash, "source_path": source_path})
        return body["size"]

    def get(self, content_hash: str, destination_path: str) -> int:
        """Copies the stored object for `content_hash` to `destination_path`."""
        body = self._post(
            "/objects/get", {"hash": content_hash, "destination_path": destination_path}
        )
        return body["size"]

    def delete(self, content_hash: str) -> bool:
        """Unconditionally removes the object.

        The caller must confirm nothing else references `content_hash`
        first (docs/storage.md#deduplication) — the engine has no
        visibility into `files`/`file_versions` rows.
        """
        return self._post("/objects/delete", {"hash": content_hash})["deleted"]

    # --- chunked uploads (Phase 5) ---------------------------------------

    def write_chunk(self, upload_id: str, index: int, source_path: str) -> None:
        """Stores `source_path`'s bytes as chunk `index` of `upload_id`.

        The engine takes ownership of `source_path` (moves it in), same
        contract as `put`. Overwrites any existing chunk at that index —
        resending a chunk the client isn't sure arrived is always safe.
        """
        self._post(
            "/chunks/write", {"upload_id": upload_id, "index": index, "source_path": source_path}
        )

    def finalize_chunks(
        self, upload_id: str, total_chunks: int, expected_hash: str | None = None
    ) -> tuple[str, int]:
        """Reconstructs `upload_id`'s chunks into a stored object.

        Returns `(content_hash, size)`. Raises `InvalidRequestError`
        (mapped from a `409`, see `_post`) if a chunk is missing or the
        reconstructed content doesn't match `expected_hash` — actually
        mapped to `ObjectCorruptedError` since the engine also returns
        `409` for both cases; either way nothing is stored and the
        caller's chunks are left in place for a retry.
        """
        payload: dict = {"upload_id": upload_id, "total_chunks": total_chunks}
        if expected_hash is not None:
            payload["expected_hash"] = expected_hash
        body = self._post("/chunks/finalize", payload)
        return body["hash"], body["size"]

    def abandon_chunks(self, upload_id: str) -> bool:
        """Deletes `upload_id`'s temp chunk directory without finalizing it."""
        return self._post("/chunks/abandon", {"upload_id": upload_id})["removed"]


def get_engine_client() -> EngineClient:
    return EngineClient()
