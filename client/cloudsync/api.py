"""HTTP client for the Personal Cloud API (and nothing else: never the engine).

Error model, which the sync engine relies on:

- `ApiUnavailable`  the server could not be reached at all (network down,
                    timeout, DNS). This is what triggers offline mode.
- `AuthError`       the login is no longer valid; the user has to log in again.
- `VersionConflict` a conditional write was refused because somebody else
                    changed the file (the server's structured 409).
- `ApiError`        any other HTTP error; `transient` says whether retrying
                    later makes sense (5xx and 429) or it never will (4xx).
"""

from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from .throttle import Throttle

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)


class ApiUnavailable(Exception):
    """The server could not be reached."""


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail

    @property
    def transient(self) -> bool:
        return self.status >= 500 or self.status == 429


class AuthError(ApiError):
    """Credentials missing, wrong or expired."""


class TwoFactorRequired(AuthError):
    """The account has two-factor login on: log in again with a code (`--otp`)."""


class VersionConflict(ApiError):
    def __init__(self, detail: str, file_id: str | None, current_version_id: str | None) -> None:
        super().__init__(409, detail)
        self.file_id = file_id
        self.current_version_id = current_version_id


@dataclass(frozen=True)
class RemoteFile:
    id: str
    path: str
    size: int
    content_hash: str
    version_id: str | None


@dataclass(frozen=True)
class RemoteSnapshot:
    folders: dict[str, str]  # path -> folder id
    files: dict[str, RemoteFile]  # path -> file


@dataclass(frozen=True)
class UploadResult:
    file_id: str
    content_hash: str
    size: int
    version_id: str | None


def _detail_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail)


def _raise_for_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 409:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict) and detail.get("code") == "version_conflict":
            raise VersionConflict(
                detail.get("message", "version conflict"),
                detail.get("file_id"),
                detail.get("current_version_id"),
            )
    if response.status_code == 401:
        raise AuthError(401, _detail_text(response))
    raise ApiError(response.status_code, _detail_text(response))


class ApiClient:
    def __init__(
        self,
        server_url: str | None = None,
        *,
        http: httpx.Client | None = None,
        access_token: str = "",
        refresh_token: str = "",
        on_tokens: Callable[[str, str], None] | None = None,
        remote_prefix: str = "",
        throttle: Throttle | None = None,
    ) -> None:
        if http is None:
            if not server_url:
                raise ValueError("server_url is required when no http client is given")
            http = httpx.Client(base_url=server_url.rstrip("/"), timeout=DEFAULT_TIMEOUT)
        self._http = http
        self._access = access_token
        self._refresh = refresh_token
        self._on_tokens = on_tokens
        self._throttle = throttle  # optional upload speed limit
        # Backup mode keeps everything under one server folder (e.g. Backups/laptop/Documents):
        # the client sees that folder as its root, so paths never carry the prefix.
        self._prefix = remote_prefix.strip("/")
        # The last snapshot and its ETag: an unchanged tree is a bodyless 304.
        self._snapshot_cache: RemoteSnapshot | None = None
        self._snapshot_etag: str | None = None

    def close(self) -> None:
        self._http.close()

    def reachable(self, timeout: float = 5.0) -> bool:
        """True if the server answers at all (any HTTP status). A cheap check that avoids a
        pointless disk scan while the laptop is off the VPN."""
        try:
            self._http.get("/api/health", timeout=timeout)
        except httpx.HTTPError:
            return False
        return True

    # --- plumbing ------------------------------------------------------------

    def _set_tokens(self, access: str, refresh: str) -> None:
        self._access, self._refresh = access, refresh
        if self._on_tokens:
            self._on_tokens(access, refresh)

    def _send(
        self,
        method: str,
        path: str,
        build: Callable[[], dict] | None = None,
        *,
        retry_auth: bool = True,
    ) -> httpx.Response:
        """One request. `build` returns fresh kwargs per attempt (so an upload
        can reopen its file if the request has to be repeated after a token refresh)."""
        kwargs = build() if build else {}
        headers = dict(kwargs.pop("headers", {}))
        if self._access:
            headers["Authorization"] = f"Bearer {self._access}"
        try:
            response = self._http.request(method, path, headers=headers, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise ApiUnavailable(str(exc) or exc.__class__.__name__) from exc

        if response.status_code == 401 and retry_auth and self._refresh and "/auth/" not in path:
            self.refresh()
            return self._send(method, path, build, retry_auth=False)
        _raise_for_error(response)
        return response

    # --- auth ------------------------------------------------------------------

    def login(self, email: str, password: str, otp: str | None = None) -> None:
        payload = {"email": email, "password": password}
        if otp:
            payload["otp"] = otp
        try:
            response = self._send(
                "POST",
                "/api/auth/login",
                lambda: {"json": payload},
                retry_auth=False,
            )
        except AuthError as exc:
            if "two_factor_required" in str(exc):
                raise TwoFactorRequired(401, "this account needs a two-factor code") from exc
            raise
        body = response.json()
        self._set_tokens(body["access_token"], body["refresh_token"])

    def refresh(self) -> None:
        if not self._refresh:
            raise AuthError(401, "not logged in")
        try:
            response = self._send(
                "POST",
                "/api/auth/refresh",
                lambda: {"json": {"refresh_token": self._refresh}},
                retry_auth=False,
            )
        except AuthError as exc:
            raise AuthError(401, "your session expired - log in again") from exc
        body = response.json()
        self._set_tokens(body["access_token"], body["refresh_token"])

    # --- tree --------------------------------------------------------------------

    def snapshot(self) -> RemoteSnapshot:
        """The server's current tree. Unchanged since last time = a cheap 304, which
        matters for polling every few seconds (and on a phone's mobile data)."""
        conditional = self._snapshot_cache is not None and self._snapshot_etag is not None
        headers = {"If-None-Match": self._snapshot_etag} if conditional else {}
        response = self._send("GET", "/api/sync/snapshot", lambda: {"headers": headers})
        if response.status_code == 304 and self._snapshot_cache is not None:
            return self._snapshot_cache

        body = response.json()
        folders = {self._inside(f["path"]): f["id"] for f in body["folders"]}
        folders.pop(None, None)
        folders.pop("", None)
        files = {
            self._inside(f["path"]): RemoteFile(
                id=f["id"],
                path=self._inside(f["path"]) or "",
                size=f["size"],
                content_hash=f["content_hash"] or "",
                version_id=f["version_id"],
            )
            for f in body["files"]
            if self._inside(f["path"]) is not None
        }
        snapshot = RemoteSnapshot(folders=folders, files=files)
        self._snapshot_cache = snapshot
        self._snapshot_etag = response.headers.get("ETag")
        return snapshot

    def ensure_folder(self, path: str) -> str | None:
        """Id of the server folder at `path` (created if missing); None for the root."""
        full = f"{self._prefix}/{path}".strip("/") if path else self._prefix
        if not full:
            return None
        body = self._send("POST", "/api/sync/folders", lambda: {"json": {"path": full}}).json()
        return body["id"]

    def _inside(self, server_path: str) -> str | None:
        """A server path relative to the prefix, or None when it is outside it."""
        if not self._prefix:
            return server_path
        if server_path == self._prefix:
            return ""
        if server_path.startswith(self._prefix + "/"):
            return server_path[len(self._prefix) + 1 :]
        return None

    # --- uploads -----------------------------------------------------------------

    def upload(
        self,
        local_path: Path,
        *,
        name: str,
        folder_id: str | None,
        content_hash: str,
        size: int,
        base_version_id: str | None,
        expect_new: bool,
        chunk_threshold: int,
        chunk_size: int,
        resume_upload_id: str | None = None,
        on_session: Callable[[str | None], None] | None = None,
    ) -> UploadResult:
        """Upload a file, conditionally: `base_version_id` = the version we started
        from, or `expect_new=True` for "nothing should exist at this path".

        Small files go in one request; large ones use the resumable chunked flow
        and report their session id through `on_session` so an interrupted upload
        can be resumed by a later call (pass it back as `resume_upload_id`).
        """
        base = "none" if expect_new else base_version_id
        if size <= chunk_threshold:
            return self._upload_small(local_path, name, folder_id, base)
        return self._upload_chunked(
            local_path,
            name,
            folder_id,
            content_hash,
            size,
            base,
            chunk_size,
            resume_upload_id,
            on_session,
        )

    @staticmethod
    def _result(body: dict) -> UploadResult:
        return UploadResult(
            file_id=body["id"],
            content_hash=body.get("content_hash") or "",
            size=body["size"],
            version_id=body.get("current_version_id"),
        )

    def _upload_small(
        self, local_path: Path, name: str, folder_id: str | None, base: str | None
    ) -> UploadResult:
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        # Small by definition (under the chunk threshold), so read it into memory:
        # no open handle is left behind, which on Windows would block a later
        # rename or delete of the file.
        content = local_path.read_bytes()
        if self._throttle:
            self._throttle.acquire(len(content))

        def build() -> dict:
            data = {"name": name}
            if folder_id:
                data["folder_id"] = folder_id
            if base:
                data["base_version_id"] = base
            return {"files": {"file": (name, content, mime)}, "data": data}

        response = self._send("POST", "/api/files/upload", build)
        return self._result(response.json())

    def _upload_chunked(
        self,
        local_path: Path,
        name: str,
        folder_id: str | None,
        content_hash: str,
        size: int,
        base: str | None,
        chunk_size: int,
        resume_upload_id: str | None,
        on_session: Callable[[str | None], None] | None,
    ) -> UploadResult:
        session = None
        if resume_upload_id:
            try:
                session = self._send("GET", f"/api/uploads/{resume_upload_id}").json()
                if session["status"] != "pending":
                    session = None
            except ApiError as exc:
                if exc.status not in (404, 409):
                    raise
                session = None  # expired or swept: start over

        if session is None:
            payload = {
                "file_name": name,
                "file_size": size,
                "chunk_size": chunk_size,
                "expected_hash": content_hash,
            }
            if folder_id:
                payload["folder_id"] = folder_id
            if base:
                payload["base_version_id"] = base
            created = self._send("POST", "/api/uploads", lambda: {"json": payload}).json()
            session = self._send("GET", f"/api/uploads/{created['id']}").json()
            if on_session:
                on_session(session["id"])

        upload_id = session["id"]
        chunk_bytes = session["chunk_size"]
        with open(local_path, "rb") as handle:
            for index in session["missing_chunk_indices"]:
                handle.seek(index * chunk_bytes)
                block = handle.read(chunk_bytes)
                if self._throttle:
                    self._throttle.acquire(len(block))
                self._send(
                    "POST",
                    f"/api/uploads/{upload_id}/chunks/{index}",
                    lambda block=block: {
                        "files": {"chunk": ("chunk", block, "application/octet-stream")}
                    },
                )

        try:
            response = self._send("POST", f"/api/uploads/{upload_id}/complete")
        except VersionConflict:
            # The server aborted the session (its chunks were consumed), so there
            # is nothing left to resume. Other errors keep the session for a retry.
            if on_session:
                on_session(None)
            raise
        if on_session:
            on_session(None)
        return self._result(response.json())

    # --- downloads ---------------------------------------------------------------

    def download(self, file_id: str, destination: Path) -> tuple[str, int]:
        """Stream a file's current content to `destination`. Returns `(sha256, size)`."""
        return self._download(f"/api/files/{file_id}/download", destination)

    def _download(self, path: str, destination: Path, retry_auth: bool = True) -> tuple[str, int]:
        headers = {"Authorization": f"Bearer {self._access}"} if self._access else {}
        digest = hashlib.sha256()
        total = 0
        try:
            with self._http.stream("GET", path, headers=headers) as response:
                if response.status_code == 401 and retry_auth and self._refresh:
                    response.read()
                    self.refresh()
                    return self._download(path, destination, retry_auth=False)
                if response.status_code >= 400:
                    response.read()
                    _raise_for_error(response)
                with open(destination, "wb") as out:
                    for block in response.iter_bytes(1024 * 1024):
                        out.write(block)
                        digest.update(block)
                        total += len(block)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise ApiUnavailable(str(exc) or exc.__class__.__name__) from exc
        return digest.hexdigest(), total

    # --- deletes -------------------------------------------------------------------

    def delete_file(self, file_id: str, base_version_id: str | None) -> bool:
        """Move a file to the server's trash, only if it is still on `base_version_id`.

        Returns False if the file was already gone (nothing to do)."""
        params = {"base_version_id": base_version_id} if base_version_id else {}
        try:
            self._send("DELETE", f"/api/files/{file_id}", lambda: {"params": params})
        except ApiError as exc:
            if exc.status == 404:
                return False
            raise
        return True
