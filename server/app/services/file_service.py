"""File/folder business logic: upload, download, rename, move, delete, trash.

Phase 4 moves file bytes into the C++ engine's content-addressable store
(see docs/storage.md). This module never touches object-storage paths
directly — every read/write of file bytes goes through
`app.services.storage_service` (docs/storage.md#the-objectstore-interface),
which calls the engine over its local HTTP API. The one exception is the
small "staging" area below: a place on the *shared* storage volume to put
bytes Python has received (from an upload, or as a scratch destination for
a download) before/after handing them to the engine — never a place file
bytes are served from directly.
"""

import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.file import File
from app.models.folder import Folder
from app.models.user import User
from app.services import activity_service, quota_service, version_service
from app.services.errors import (
    ConflictError,
    NotFoundError,
    StorageError,
    ValidationError,
    VersionConflictError,
)
from app.services.storage_service import get_storage_service

settings = get_settings()

# NotFoundError/ConflictError/ValidationError/StorageError are imported from
# app.services.errors above but stay reachable as `file_service.<Name>` (the
# API layer and upload_service rely on that); see errors.py for why they moved.


def _staging_dir() -> Path:
    return Path(settings.storage_root) / "staging"


def _staging_path(suffix: str = "") -> Path:
    return _staging_dir() / f"{uuid.uuid4().hex}{suffix}"


def _validate_filename(name: str | None) -> str:
    if name is None:
        raise ValidationError("a file name is required")
    stripped = name.strip()
    if not stripped:
        raise ValidationError("name must not be empty")
    if len(stripped) > 255:
        raise ValidationError("name must be at most 255 characters")
    if "/" in stripped or "\\" in stripped:
        raise ValidationError("name must not contain '/' or '\\'")
    if stripped in (".", ".."):
        raise ValidationError("name must not be '.' or '..'")
    if "\x00" in stripped:
        raise ValidationError("name must not contain a null byte")
    return stripped


# --- folders -----------------------------------------------------------


def _get_folder_or_404(db: Session, owner: User, folder_id: uuid.UUID) -> Folder:
    folder = db.get(Folder, folder_id)
    if folder is None or folder.owner_id != owner.id:
        raise NotFoundError("folder not found")
    return folder


def _folder_name_taken(
    db: Session,
    owner: User,
    parent_id: uuid.UUID | None,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    stmt = select(Folder).where(
        Folder.owner_id == owner.id,
        Folder.parent_id == parent_id,
        Folder.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(Folder.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _would_create_cycle(
    db: Session, folder_id: uuid.UUID, new_parent_id: uuid.UUID | None
) -> bool:
    """True if setting `folder_id`'s parent to `new_parent_id` creates a cycle.

    A folder can't become its own descendant's parent — walk up from the
    proposed new parent to the root; hitting `folder_id` means the move
    would nest the folder inside itself.
    """
    current = new_parent_id
    seen: set[uuid.UUID] = set()
    while current is not None:
        if current == folder_id:
            return True
        if current in seen:
            break  # defensive: don't loop forever over corrupt data
        seen.add(current)
        parent = db.get(Folder, current)
        if parent is None:
            break
        current = parent.parent_id
    return False


def create_folder(
    db: Session, owner: User, name: str, parent_id: uuid.UUID | None
) -> Folder:
    if parent_id is not None:
        _get_folder_or_404(db, owner, parent_id)

    if _folder_name_taken(db, owner, parent_id, name):
        raise ConflictError("a folder with that name already exists here")

    folder = Folder(owner_id=owner.id, parent_id=parent_id, name=name)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def get_folder(db: Session, owner: User, folder_id: uuid.UUID) -> Folder:
    return _get_folder_or_404(db, owner, folder_id)


def list_subfolders(db: Session, owner: User, parent_id: uuid.UUID | None) -> list[Folder]:
    stmt = (
        select(Folder)
        .where(Folder.owner_id == owner.id, Folder.parent_id == parent_id)
        .order_by(Folder.name)
    )
    return list(db.execute(stmt).scalars().all())


def update_folder(
    db: Session, owner: User, folder_id: uuid.UUID, data: dict
) -> Folder:
    folder = _get_folder_or_404(db, owner, folder_id)

    new_parent_id = folder.parent_id
    if "parent_id" in data:
        new_parent_id = data["parent_id"]
        if new_parent_id is not None:
            _get_folder_or_404(db, owner, new_parent_id)
        if new_parent_id == folder.id or _would_create_cycle(db, folder.id, new_parent_id):
            raise ConflictError("cannot move a folder into itself or one of its own subfolders")

    new_name = data.get("name", folder.name)

    if (new_name, new_parent_id) != (folder.name, folder.parent_id) and _folder_name_taken(
        db, owner, new_parent_id, new_name, exclude_id=folder.id
    ):
        raise ConflictError("a folder with that name already exists here")

    folder.name = new_name
    folder.parent_id = new_parent_id
    db.commit()
    db.refresh(folder)
    return folder


def delete_folder(db: Session, owner: User, folder_id: uuid.UUID) -> None:
    folder = _get_folder_or_404(db, owner, folder_id)

    has_subfolder = (
        db.execute(select(Folder.id).where(Folder.parent_id == folder.id).limit(1))
        .scalars()
        .first()
        is not None
    )
    has_file = (
        db.execute(
            select(File.id)
            .where(File.folder_id == folder.id, File.deleted_at.is_(None))
            .limit(1)
        )
        .scalars()
        .first()
        is not None
    )
    if has_subfolder or has_file:
        # Rule 5: never silently destroy data — refuse rather than cascade.
        raise ConflictError("folder is not empty")

    # Trashed files may still point at this folder. Detach them (they restore
    # to the root, see trash_service.restore_file) rather than letting the
    # foreign key block the delete or silently dropping them (Rule 5).
    db.execute(
        update(File)
        .where(File.folder_id == folder.id, File.deleted_at.is_not(None))
        .values(folder_id=None)
    )

    db.delete(folder)
    db.commit()


# --- files ---------------------------------------------------------------


def _get_file_or_404(db: Session, owner: User, file_id: uuid.UUID) -> File:
    file = db.get(File, file_id)
    if file is None or file.owner_id != owner.id or file.deleted_at is not None:
        raise NotFoundError("file not found")
    return file


def list_files(db: Session, owner: User, folder_id: uuid.UUID | None) -> list[File]:
    stmt = (
        select(File)
        .where(
            File.owner_id == owner.id,
            File.folder_id == folder_id,
            File.deleted_at.is_(None),
        )
        .order_by(File.name)
    )
    return list(db.execute(stmt).scalars().all())


async def upload_file(
    db: Session,
    owner: User,
    upload: UploadFile,
    folder_id: uuid.UUID | None,
    name: str | None = None,
    base_version_id: uuid.UUID | None = None,
    expect_new: bool = False,
    taken_at: datetime | None = None,
) -> File:
    resolved_name = _validate_filename(name or upload.filename)

    if folder_id is not None:
        _get_folder_or_404(db, owner, folder_id)

    content = await upload.read()
    quota_service.ensure_room(db, owner, len(content))
    mime_type = upload.content_type or mimetypes.guess_type(resolved_name)[0]

    # Stage the bytes on the shared storage volume so the engine (a
    # separate process, possibly a separate container) can read them,
    # then hand ownership to the engine's content-addressable store. Both
    # calls go through storage_service — file_service never touches
    # object-storage paths itself (docs/storage.md).
    staging_path = _staging_path()
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_bytes(content)

    storage = get_storage_service()
    try:
        content_hash = storage.hash_file(staging_path)
        storage.store(content_hash, staging_path)  # consumes staging_path
    except Exception as exc:
        staging_path.unlink(missing_ok=True)
        raise StorageError(f"could not store uploaded file: {exc}") from exc

    # Creates the file (version 1), or appends a new version if the owner
    # already has a live file with this name in this folder, or does nothing
    # if the bytes are identical (see version_service.save_content).
    try:
        file = version_service.save_content(
            db,
            owner,
            folder_id=folder_id,
            name=resolved_name,
            mime_type=mime_type,
            size=len(content),
            content_hash=content_hash,
            base_version_id=base_version_id,
            expect_new=expect_new,
            taken_at=taken_at,
        )
        db.commit()
    except Exception:
        db.rollback()
        # The physical object may now be unreferenced by any row, but we
        # never delete it here — another row could reference the same
        # hash, and there's no reference-counted GC yet (Rule 5: never
        # silently destroy data; see storage_manager.hpp's docstring).
        raise
    db.refresh(file)
    return file


def get_file(db: Session, owner: User, file_id: uuid.UUID) -> File:
    return _get_file_or_404(db, owner, file_id)


def prepare_download(file: File, content_hash: str | None = None) -> Path:
    """Copies `file`'s bytes out of the engine's store to a fresh staging path.

    Downloads the current content by default; pass `content_hash` to fetch an
    older version's bytes instead (the file's name is still used for the
    staging path, so the download keeps its filename).

    Returns the staging path so the API layer can stream it in a response
    and then delete it (see the `BackgroundTask` in `app/api/files.py`) —
    this function doesn't clean up after itself, since the caller controls
    how long the file needs to stay around to be served.

    Raises `StorageError` wrapping the underlying engine failure (missing
    object, corrupted object, engine unreachable).
    """
    destination = _staging_path(suffix=f"-{file.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    storage = get_storage_service()
    try:
        storage.retrieve(content_hash or file.content_hash, destination)
    except Exception as exc:
        raise StorageError(f"could not retrieve stored file: {exc}") from exc
    return destination


def update_file(db: Session, owner: User, file_id: uuid.UUID, data: dict) -> File:
    file = _get_file_or_404(db, owner, file_id)

    new_folder_id = file.folder_id
    if "folder_id" in data:
        new_folder_id = data["folder_id"]
        if new_folder_id is not None:
            _get_folder_or_404(db, owner, new_folder_id)

    new_name = data.get("name", file.name)

    # Versioning treats (owner, folder, name) as a file's identity: uploading
    # that name again adds a version. Two live files sharing one would make
    # that ambiguous, so reject the rename/move instead (Rule 5: surface it,
    # don't guess which file the user meant).
    if (new_name, new_folder_id) != (file.name, file.folder_id):
        clash = version_service.find_live_file(db, owner, new_folder_id, new_name)
        if clash is not None and clash.id != file.id:
            raise ConflictError("a file with that name already exists in that folder")

    old_name, old_folder = file.name, file.folder_id
    file.name = new_name
    file.folder_id = new_folder_id
    if new_name != old_name:
        activity_service.record(
            db, owner.id, "renamed", file_id=file.id, file_name=new_name, detail=f"was {old_name}"
        )
    if new_folder_id != old_folder:
        activity_service.record(db, owner.id, "moved", file_id=file.id, file_name=new_name)

    db.commit()
    db.refresh(file)
    return file


def delete_file(
    db: Session,
    owner: User,
    file_id: uuid.UUID,
    base_version_id: uuid.UUID | None = None,
) -> None:
    """Moves a file to the trash.

    With `base_version_id`, only if the file is still on that version - a sync
    client uses this so deleting a file locally can never trash an edit made on
    another device in the meantime (raises `VersionConflictError`).
    """
    file = _get_file_or_404(db, owner, file_id)
    if base_version_id is not None and file.current_version_id != base_version_id:
        raise VersionConflictError(
            "the file was changed since the version this delete was based on",
            file_id=file.id,
            current_version_id=file.current_version_id,
        )
    file.deleted_at = datetime.now(UTC)
    activity_service.record(db, owner.id, "trashed", file_id=file.id, file_name=file.name)
    db.commit()


def search(
    db: Session, owner: User, query: str, limit: int = 50
) -> tuple[list[Folder], list[File]]:
    pattern = f"%{query}%"
    folders = list(
        db.execute(
            select(Folder)
            .where(Folder.owner_id == owner.id, Folder.name.ilike(pattern))
            .order_by(Folder.name)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    files = list(
        db.execute(
            select(File)
            .where(
                File.owner_id == owner.id,
                File.deleted_at.is_(None),
                File.name.ilike(pattern),
            )
            .order_by(File.name)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return folders, files
