"""Resumable chunked upload sessions (Phase 5).

See docs/architecture.md#10-chunked-uploads and #11-chunk-storage. Like
`file_service`, this module never touches object- or chunk-storage paths
directly — every chunk write/finalize/abandon goes through
`app.services.storage_service`, which calls the engine's `/chunks/*` HTTP
API. The only local filesystem access here is staging an individual
chunk's bytes on the shared storage volume before handing it to the
engine, exactly like `file_service.upload_file` stages a whole file.
"""

import math
import mimetypes
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.file import File
from app.models.upload import Upload
from app.models.user import User
from app.services import quota_service, version_service
from app.services.engine_client import EngineError, ObjectCorruptedError
from app.services.errors import VersionConflictError
from app.services.file_service import (
    ConflictError,
    NotFoundError,
    StorageError,
    ValidationError,
    _get_folder_or_404,
    _staging_path,
    _validate_filename,
)
from app.services.storage_service import get_storage_service

settings = get_settings()


# One chunk is held in memory while it is staged, and a session's progress is a row of chunk
# numbers, so both are bounded. Clients use 5 MiB chunks.
MAX_CHUNK_BYTES = 64 * 1024 * 1024
MAX_CHUNKS = 20_000


def _get_upload_or_404(db: Session, owner: User, upload_id: uuid.UUID) -> Upload:
    upload = db.get(Upload, upload_id)
    if upload is None or upload.owner_id != owner.id:
        raise NotFoundError("upload session not found")
    return upload


def _ensure_active(upload: Upload) -> None:
    """Raises ConflictError if `upload` can no longer accept chunks or be completed.

    A session past its `expires_at` is treated as already gone even if the
    sweep (see `sweep_expired_uploads` below) hasn't run yet — never trust
    wall-clock timing to have happened on schedule.
    """
    now = datetime.now(UTC)
    expires_at = upload.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if upload.status != "pending" or expires_at < now:
        raise ConflictError(f"upload session is {upload.status} and no longer accepts chunks")


def create_session(
    db: Session,
    owner: User,
    file_name: str,
    file_size: int,
    chunk_size: int,
    folder_id: uuid.UUID | None,
    expected_hash: str | None,
    base_version_id: str | None = None,
    taken_at: datetime | None = None,
) -> Upload:
    resolved_name = _validate_filename(file_name)

    if folder_id is not None:
        _get_folder_or_404(db, owner, folder_id)

    if file_size <= 0:
        raise ValidationError("file_size must be positive")
    if chunk_size <= 0:
        raise ValidationError("chunk_size must be positive")
    if chunk_size > MAX_CHUNK_BYTES:
        raise ValidationError(f"chunk_size must be at most {MAX_CHUNK_BYTES} bytes")
    # Reject a malformed precondition now, not after the whole file is uploaded.
    version_service.parse_base_version(base_version_id)

    quota_service.ensure_room(db, owner, file_size)

    total_chunks = math.ceil(file_size / chunk_size)
    if total_chunks > MAX_CHUNKS:
        raise ValidationError(
            f"too many chunks ({total_chunks}); use a larger chunk_size "
            f"(at most {MAX_CHUNKS} chunks)"
        )

    upload = Upload(
        id=uuid.uuid4(),
        owner_id=owner.id,
        folder_id=folder_id,
        file_name=resolved_name,
        file_size=file_size,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        expected_hash=expected_hash,
        base_version_id=base_version_id,
        taken_at=taken_at,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=settings.upload_session_expire_hours),
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def get_status(db: Session, owner: User, upload_id: uuid.UUID) -> Upload:
    return _get_upload_or_404(db, owner, upload_id)


async def write_chunk(
    db: Session, owner: User, upload_id: uuid.UUID, index: int, chunk: UploadFile
) -> Upload:
    upload = _get_upload_or_404(db, owner, upload_id)
    _ensure_active(upload)

    if index < 0 or index >= upload.total_chunks:
        raise ValidationError(
            f"chunk index {index} out of range for {upload.total_chunks} total chunks"
        )

    # Every chunk must be exactly the size the session promised (the last one is the remainder).
    # Without this a client could declare a tiny file to pass the quota check and then send an
    # enormous chunk.
    expected = min(upload.chunk_size, upload.file_size - index * upload.chunk_size)
    content = await chunk.read(expected + 1)
    if len(content) != expected:
        got = "more" if len(content) > expected else str(len(content))
        raise ValidationError(f"chunk {index} must be exactly {expected} bytes (got {got})")
    staging_path = _staging_path()
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_bytes(content)

    storage = get_storage_service()
    try:
        storage.write_chunk(str(upload.id), index, staging_path)  # consumes staging_path
    except EngineError as exc:
        staging_path.unlink(missing_ok=True)
        raise StorageError(f"could not store chunk {index}: {exc}") from exc

    upload.mark_chunk_received(index)
    db.commit()
    db.refresh(upload)
    return upload


def complete_upload(db: Session, owner: User, upload_id: uuid.UUID) -> File:
    upload = _get_upload_or_404(db, owner, upload_id)
    _ensure_active(upload)

    storage = get_storage_service()
    try:
        content_hash, size = storage.finalize_upload(
            str(upload.id), upload.total_chunks, upload.expected_hash
        )
    except ObjectCorruptedError as exc:
        # Covers both "a chunk is missing" and "reconstructed content
        # doesn't match expected_hash" — the engine maps both to 409
        # (see engine_server.cpp), which EngineClient._post surfaces as
        # ObjectCorruptedError. Either way nothing was stored and the
        # client's chunks are untouched, so this is a conflict the client
        # can act on (resend the missing chunk, or re-check its hash),
        # not a fatal error.
        raise ConflictError(f"could not complete upload: {exc}") from exc
    except EngineError as exc:
        raise StorageError(f"could not complete upload: {exc}") from exc

    mime_type = mimetypes.guess_type(upload.file_name)[0]
    base_version_id, expect_new = version_service.parse_base_version(upload.base_version_id)
    upload.status = "completed"
    try:
        # Same rule as a plain upload: a new file, or the next version of the
        # live file with this name in this folder (version_service.save_content).
        file = version_service.save_content(
            db,
            owner,
            folder_id=upload.folder_id,
            name=upload.file_name,
            mime_type=mime_type,
            size=size,
            content_hash=content_hash,
            base_version_id=base_version_id,
            expect_new=expect_new,
            taken_at=upload.taken_at,
        )
        db.commit()
    except VersionConflictError:
        # Someone else changed the file while this was uploading. The chunks
        # were already consumed by the finalize, so the session can't be
        # retried: mark it aborted so the client starts a fresh upload (usually
        # of a conflict copy) instead of re-completing it.
        db.rollback()
        upload = _get_upload_or_404(db, owner, upload_id)
        upload.status = "aborted"
        db.commit()
        raise
    except Exception:
        db.rollback()
        # Same reasoning as file_service.upload_file: the physical object
        # may now be unreferenced by any row, but it's never deleted here
        # (no reference-counted GC yet — Rule 5).
        raise
    db.refresh(file)
    return file


def abandon_upload(db: Session, owner: User, upload_id: uuid.UUID) -> None:
    """Cancels an in-progress upload: deletes its temp chunks and its session row."""
    upload = _get_upload_or_404(db, owner, upload_id)

    storage = get_storage_service()
    try:
        storage.abandon_upload(str(upload.id))
    except EngineError as exc:
        raise StorageError(f"could not clean up upload chunks: {exc}") from exc

    db.delete(upload)
    db.commit()


def sweep_expired_uploads(db: Session) -> int:
    """Deletes expired, still-pending upload sessions and their temp chunks.

    Meant to be run periodically (a cron-style job, or triggered
    alongside a healthcheck — see docs/architecture.md#11-chunk-storage
    and CLAUDE.md's Phase 5 notes); not wired to a scheduler itself, since
    this project deliberately avoids infrastructure it doesn't need
    (Rule 2). Returns how many sessions were swept.
    """
    now = datetime.now(UTC)
    expired = list(
        db.execute(
            select(Upload).where(Upload.status == "pending", Upload.expires_at < now)
        ).scalars()
    )

    storage = get_storage_service()
    swept = 0
    for upload in expired:
        try:
            storage.abandon_upload(str(upload.id))
        except EngineError:
            # Best-effort cleanup: if the engine can't be reached right
            # now, leave the row (and its chunks) for the next sweep
            # rather than losing track of them (Rule 5: never silently
            # lose track of data that might still need cleaning up).
            continue
        db.delete(upload)
        swept += 1

    db.commit()
    return swept
