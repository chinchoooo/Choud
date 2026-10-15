"""Trash: list, restore, permanently delete (Phase 6).

`file_service.delete_file` only sets `files.deleted_at`; everything that
happens to a file *after* that lives here.

Rules (CLAUDE.md "Phase 6 decisions"):

- Trash holds files only. There is no auto-expiry — a file leaves the trash
  only when the owner restores or purges it.
- Restore puts the file back in its original folder. If that folder no
  longer exists it goes to the root; if the name is taken there by a live
  file, a suffix is added: `report.pdf` -> `report (restored).pdf`, then
  `report (restored 2).pdf`, ... Nothing is overwritten.
- Purge removes the file and all its version rows, then deletes each stored
  object *only if nothing else still references that content hash*. Objects
  are shared across users by deduplication, so "nothing else" means every
  file and version of every owner.

Known limitation: the reference check and the object delete are not atomic
with a concurrent upload of identical bytes by someone else. If that upload
has stored the object but not yet committed its row at the instant of the
check, the object can be deleted underneath it. The window is tiny and a
later download of that file would fail loudly (Rule 5: never silently), not
return wrong data; closing it properly belongs with the garbage-collection
work (Phase 15), which needs a reference-counted delete in the engine.
"""

import logging
import posixpath
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion
from app.models.folder import Folder
from app.models.user import User
from app.services import activity_service, version_service
from app.services.engine_client import EngineError
from app.services.errors import NotFoundError
from app.services.storage_service import get_storage_service

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 255


def _get_trashed_or_404(db: Session, owner: User, file_id: uuid.UUID) -> File:
    file = db.get(File, file_id)
    # Same 404 for "doesn't exist", "someone else's" and "not in the trash".
    if file is None or file.owner_id != owner.id or file.deleted_at is None:
        raise NotFoundError("file not found in trash")
    return file


def list_trash(db: Session, owner: User) -> list[File]:
    """The owner's trashed files, most recently deleted first."""
    return list(
        db.execute(
            select(File)
            .where(File.owner_id == owner.id, File.deleted_at.is_not(None))
            .order_by(File.deleted_at.desc(), File.name)
        )
        .scalars()
        .all()
    )


def _restored_name(name: str, attempt: int) -> str:
    """`report.pdf` -> `report (restored).pdf` (attempt 1), `(restored 2)` (attempt 2)..."""
    stem, ext = posixpath.splitext(name)
    tag = " (restored)" if attempt == 1 else f" (restored {attempt})"
    # Keep the result within the 255-character name limit by trimming the stem.
    stem = stem[: MAX_NAME_LENGTH - len(ext) - len(tag)]
    return f"{stem}{tag}{ext}"


def restore_file(db: Session, owner: User, file_id: uuid.UUID) -> File:
    """Takes a file out of the trash. Commits."""
    file = _get_trashed_or_404(db, owner, file_id)

    folder_id = file.folder_id
    if folder_id is not None:
        folder = db.get(Folder, folder_id)
        if folder is None or folder.owner_id != owner.id:
            folder_id = None  # original folder is gone -> root

    name = file.name
    attempt = 0
    while version_service.find_live_file(db, owner, folder_id, name) is not None:
        attempt += 1
        name = _restored_name(file.name, attempt)

    file.folder_id = folder_id
    file.name = name
    file.deleted_at = None
    activity_service.record(db, owner.id, "restored", file_id=file.id, file_name=file.name)
    db.commit()
    db.refresh(file)
    return file


def _hash_is_referenced(db: Session, content_hash: str) -> bool:
    in_files = (
        db.execute(select(File.id).where(File.content_hash == content_hash).limit(1))
        .scalars()
        .first()
    )
    if in_files is not None:
        return True
    in_versions = (
        db.execute(
            select(FileVersion.id).where(FileVersion.content_hash == content_hash).limit(1)
        )
        .scalars()
        .first()
    )
    return in_versions is not None


def purge_file(db: Session, owner: User, file_id: uuid.UUID) -> int:
    """Permanently deletes a trashed file and any objects only it used. Commits.

    Returns how many stored objects were physically deleted. Only files that
    are already in the trash can be purged — a live file must be deleted
    (trashed) first.

    The database rows are removed first and committed; objects are deleted
    afterwards. If the engine is unreachable or a delete fails, the rows are
    already gone and the object is simply left behind as an unreferenced
    orphan for a future garbage-collection pass — leaking disk space is
    always preferred over deleting something that might still be needed.
    """
    file = _get_trashed_or_404(db, owner, file_id)

    versions = list(
        db.execute(select(FileVersion).where(FileVersion.file_id == file.id)).scalars()
    )
    hashes = {v.content_hash for v in versions}
    if file.content_hash:
        hashes.add(file.content_hash)

    activity_service.record(db, owner.id, "purged", file_id=file.id, file_name=file.name)
    for version in versions:
        db.delete(version)
    # File and FileVersion have no ORM relationship(), so SQLAlchemy can't
    # order these DELETEs itself: flush the versions first or PostgreSQL
    # rejects deleting the file while file_versions still references it.
    db.flush()
    db.delete(file)
    db.commit()

    storage = get_storage_service()
    removed = 0
    for content_hash in sorted(hashes):
        if _hash_is_referenced(db, content_hash):
            continue  # another file or version (maybe another user's) still uses it
        try:
            if storage.remove(content_hash):
                removed += 1
        except EngineError:
            logger.warning(
                "could not delete unreferenced object %s; leaving it for garbage collection",
                content_hash,
            )
    return removed
