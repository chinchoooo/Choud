"""File version history: create, list, restore (Phase 6).

Design rules (see CLAUDE.md "Phase 6 decisions" and docs/architecture.md
#12-versioning):

- Uploading a file with the same name into the same folder adds a new
  version of the existing file instead of creating a second file.
- Uploading *identical bytes* under the same name is a no-op: the existing
  file is returned unchanged. A version with no content change is noise.
- History is append-only. Restoring an old version appends a *new* version
  that points at the old content; nothing is rewritten or deleted.
- `files.content_hash` / `size` / `storage_key` always mirror the version
  `files.current_version_id` points at, so hot read paths never join here.

Functions here take an already-authorised `File` (the API layer gets it from
`file_service.get_file`, which enforces ownership and hides trashed files).
That keeps this module independent of `file_service`, which calls into it on
every upload. Nothing here commits unless its docstring says so — the caller
owns the transaction, so a version row and the change that caused it land
atomically.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion
from app.models.user import User
from app.services import activity_service
from app.services.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
    VersionConflictError,
)

NO_FILE = "none"


def parse_base_version(raw: str | None) -> tuple[uuid.UUID | None, bool]:
    """Interprets a client's `base_version_id` string as `(base_version_id, expect_new)`.

    `None`/empty -> no precondition. `"none"` -> the caller expects no live file
    at the path (create-only). A UUID -> the version the caller started from.
    Anything else raises `ValidationError`.
    """
    if raw is None or raw == "":
        return None, False
    if raw == NO_FILE:
        return None, True
    try:
        return uuid.UUID(raw), False
    except ValueError as exc:
        raise ValidationError(f"base_version_id must be a version id or '{NO_FILE}'") from exc


def _next_version_number(db: Session, file_id: uuid.UUID) -> int:
    current_max = db.execute(
        select(func.max(FileVersion.version_number)).where(FileVersion.file_id == file_id)
    ).scalar_one()
    return (current_max or 0) + 1


def _append_version(
    db: Session,
    file: File,
    *,
    content_hash: str,
    size: int,
    created_by: uuid.UUID,
    restored_from_version: int | None = None,
) -> FileVersion:
    """Adds a version row and points `file` at it. Flushes; does not commit."""
    version = FileVersion(
        id=uuid.uuid4(),
        file_id=file.id,
        version_number=_next_version_number(db, file.id),
        content_hash=content_hash,
        size=size,
        restored_from_version=restored_from_version,
        created_by=created_by,
    )
    db.add(version)

    if file.content_hash != content_hash:
        file.thumbhash = None  # the picture changed; the placeholder is made again
    file.content_hash = content_hash
    # storage_key is "the key used to locate bytes in the storage backend",
    # which has been the content hash since Phase 4.
    file.storage_key = content_hash
    file.size = size
    file.current_version_id = version.id
    db.flush()
    return version


def find_live_file(
    db: Session, owner: User, folder_id: uuid.UUID | None, name: str
) -> File | None:
    """The owner's non-trashed file called `name` in `folder_id`, if any.

    If rename/move ever let two live files share a name (they can't — see
    `file_service.update_file`), the oldest wins so behaviour stays stable.
    """
    return (
        db.execute(
            select(File)
            .where(
                File.owner_id == owner.id,
                File.folder_id == folder_id,
                File.name == name,
                File.deleted_at.is_(None),
            )
            .order_by(File.created_at, File.id)
            .limit(1)
        )
        .scalars()
        .first()
    )


def save_content(
    db: Session,
    owner: User,
    *,
    folder_id: uuid.UUID | None,
    name: str,
    mime_type: str | None,
    size: int,
    content_hash: str,
    base_version_id: uuid.UUID | None = None,
    expect_new: bool = False,
    taken_at: datetime | None = None,
    modified_at: datetime | None = None,
) -> File:
    """Records `content_hash` as the content of `name` in `folder_id`.

    - No live file by that name: creates the file with version 1.
    - Live file with different content: appends the next version.
    - Live file with identical content: returns it unchanged (no new version).

    Optional preconditions make this a compare-and-swap, which is what lets a
    sync client detect that someone else changed the file since it last looked
    (and avoid silently overwriting them):

    - `base_version_id`: the version the caller started from. If the live file
      is on a different version, raises `VersionConflictError`.
    - `expect_new`: the caller believes no live file exists at this path. If
      one does, raises `VersionConflictError`.

    Identical content is never a conflict - both sides already agree. If the
    file is gone while `base_version_id` is set, the content is simply saved as
    a new file: the other side deleted it, and the caller's data must not be
    dropped (Rule 5).

    The bytes must already be in the object store. Flushes but does not
    commit; the caller commits (and rolls back on failure).
    """
    existing = find_live_file(db, owner, folder_id, name)

    if existing is None:
        file = File(
            id=uuid.uuid4(),
            owner_id=owner.id,
            folder_id=folder_id,
            name=name,
            mime_type=mime_type,
            size=size,
            content_hash=content_hash,
            storage_key=content_hash,
            taken_at=taken_at,
            modified_at=modified_at,
        )
        db.add(file)
        db.flush()  # the version row's FK needs the file row to exist
        _append_version(db, file, content_hash=content_hash, size=size, created_by=owner.id)
        activity_service.record(db, owner.id, "uploaded", file_id=file.id, file_name=file.name)
        return file

    if existing.content_hash == content_hash:
        # Same bytes: no new version, but the device's dates are still worth recording.
        if modified_at is not None:
            existing.modified_at = modified_at
        if taken_at is not None and existing.taken_at is None:
            existing.taken_at = taken_at
        return existing

    if expect_new:
        raise VersionConflictError(
            "a file already exists at that path",
            file_id=existing.id,
            current_version_id=existing.current_version_id,
        )
    if base_version_id is not None and existing.current_version_id != base_version_id:
        raise VersionConflictError(
            "the file was changed since the version this upload was based on",
            file_id=existing.id,
            current_version_id=existing.current_version_id,
        )

    if mime_type:
        existing.mime_type = mime_type
    if modified_at is not None:
        existing.modified_at = modified_at
    _append_version(db, existing, content_hash=content_hash, size=size, created_by=owner.id)
    activity_service.record(
        db, owner.id, "new_version", file_id=existing.id, file_name=existing.name
    )
    return existing


def list_versions(db: Session, file: File) -> list[FileVersion]:
    """All versions of `file`, newest first."""
    return list(
        db.execute(
            select(FileVersion)
            .where(FileVersion.file_id == file.id)
            .order_by(FileVersion.version_number.desc())
        )
        .scalars()
        .all()
    )


def get_version(db: Session, file: File, version_id: uuid.UUID) -> FileVersion:
    version = db.get(FileVersion, version_id)
    if version is None or version.file_id != file.id:
        # Same 404 whether it never existed or belongs to another file, so
        # ids from other files can't be probed.
        raise NotFoundError("version not found")
    return version


def restore_version(db: Session, file: File, version_id: uuid.UUID, user: User) -> FileVersion:
    """Makes `version_id`'s content current by appending a *new* version.

    Commits. Raises `NotFoundError` for an unknown version and
    `ConflictError` if that version already is the current one.
    """
    old = get_version(db, file, version_id)
    if file.current_version_id == old.id:
        raise ConflictError("that version is already the current version")

    new_version = _append_version(
        db,
        file,
        content_hash=old.content_hash,
        size=old.size,
        created_by=user.id,
        restored_from_version=old.version_number,
    )
    db.commit()
    db.refresh(new_version)
    return new_version
