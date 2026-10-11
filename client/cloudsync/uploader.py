"""Push a local file to the server as a conditional write.

The scan that decided to upload recorded the file's size and modification time.
Before sending anything we check the file still matches, so we never upload
bytes whose hash we did not compute. What gets remembered afterwards is what the
*server* says it stored (its hash and version), with the scan-time stat: if the
file changed after the scan the stat will no longer match and the next cycle
simply re-hashes and uploads again.
"""

from __future__ import annotations

from pathlib import Path

from .api import ApiClient, UploadResult
from .database import StateDB
from .paths import safe_join, split_parent
from .scanner import LocalFile


class FileChangedLocally(Exception):
    """The file was modified between the scan and the upload; retry next cycle."""


def upload_file(
    api: ApiClient,
    db: StateDB,
    root: Path,
    local: LocalFile,
    *,
    folder_id: str | None,
    base_version_id: str | None,
    expect_new: bool,
    chunk_threshold: int,
    chunk_size: int,
) -> UploadResult:
    path = safe_join(root, local.path)
    stat = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (local.size, local.mtime_ns):
        raise FileChangedLocally(f"{local.path} changed after it was scanned")

    _, name = split_parent(local.path)
    resume_id = db.get_upload(local.path, local.content_hash)

    def remember(upload_id: str | None) -> None:
        # Persist the chunked-upload session so an interrupted upload (even
        # across a restart) resumes with only the missing chunks.
        if upload_id:
            db.put_upload(local.path, local.content_hash, upload_id)
        else:
            db.delete_upload(local.path, local.content_hash)

    return api.upload(
        path,
        name=name,
        folder_id=folder_id,
        content_hash=local.content_hash,
        size=local.size,
        base_version_id=base_version_id,
        expect_new=expect_new,
        chunk_threshold=chunk_threshold,
        chunk_size=chunk_size,
        resume_upload_id=resume_id,
        on_session=remember,
    )
