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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion
from app.models.user import User
from app.services.errors import ConflictError, NotFoundError


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
) -> File:
    """Records `content_hash` as the content of `name` in `folder_id`.

    - No live file by that name: creates the file with version 1.
    - Live file with different content: appends the next version.
    - Live file with identical content: returns it unchanged (no new version).

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
        )
        db.add(file)
        db.flush()  # the version row's FK needs the file row to exist
        _append_version(db, file, content_hash=content_hash, size=size, created_by=owner.id)
        return file

    if existing.content_hash == content_hash:
        return existing

    if mime_type:
        existing.mime_type = mime_type
    _append_version(db, existing, content_hash=content_hash, size=size, created_by=owner.id)
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
