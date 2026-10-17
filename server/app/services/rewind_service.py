"""Rewind: see, and put back, your files as they were at an earlier moment (a Choud original).

Every change already leaves a trail: each content change is a version row with a timestamp, and
deleted files wait in the trash. Rewind reads that trail:

* **browse** a folder as it looked at time T: which files existed, and with which content;
* **restore** one file to how it was at T;
* **restore a whole folder tree** to how it was at T. This is the "undo" for a bad sync, an
  accidental mass delete, or ransomware that overwrote your files.

Nothing is ever destroyed by a rewind. Putting a file back adds a *new* version (so the version you
rewound away from stays in its history), and files created *after* T are left exactly as they are.

Limits, stated honestly: names and folder locations are the current ones (renames and moves are not
recorded), and a file that was permanently purged cannot come back.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion
from app.models.folder import Folder
from app.models.user import User
from app.services import activity_service, trash_service, version_service
from app.services.errors import NotFoundError


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass
class PastFile:
    file: File
    version: FileVersion  # the content the file had at the chosen time
    changed: bool  # its content today differs from then
    trashed: bool  # it is in the trash today


@dataclass
class RestoreReport:
    restored_content: int = 0  # files whose old content was put back as a new version
    undeleted: int = 0  # files taken out of the trash
    unchanged: int = 0  # already as they were
    newer_untouched: int = 0  # created after the chosen time, left alone
    files: list[str] = field(default_factory=list)  # names affected (capped)


def _versions_by_file(db: Session, file_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[FileVersion]]:
    grouped: dict[uuid.UUID, list[FileVersion]] = {}
    for start in range(0, len(file_ids), 500):
        rows = db.execute(
            select(FileVersion)
            .where(FileVersion.file_id.in_(file_ids[start : start + 500]))
            .order_by(FileVersion.file_id, FileVersion.version_number)
        ).scalars()
        for version in rows:
            grouped.setdefault(version.file_id, []).append(version)
    return grouped


def _as_of(file: File, versions: list[FileVersion], at: datetime) -> FileVersion | None:
    """The version `file` had at `at`, or None if it did not exist yet (or was already trashed)."""
    if not versions:
        return None
    if file.deleted_at is not None and _aware(file.deleted_at) <= at:
        return None  # it was deleted before the chosen time
    past = [v for v in versions if _aware(v.created_at) <= at]
    return past[-1] if past else None


def _owned_folder(db: Session, owner: User, folder_id: uuid.UUID | None) -> Folder | None:
    if folder_id is None:
        return None
    folder = db.get(Folder, folder_id)
    if folder is None or folder.owner_id != owner.id:
        raise NotFoundError("folder not found")
    return folder


def _subtree_folder_ids(db: Session, owner: User, root: uuid.UUID | None) -> set[uuid.UUID | None]:
    """The folder and everything below it (None stands for the account root, i.e. everything)."""
    folders = db.execute(select(Folder).where(Folder.owner_id == owner.id)).scalars().all()
    if root is None:
        return {None, *(f.id for f in folders)}
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for folder in folders:
        children.setdefault(folder.parent_id, []).append(folder.id)
    found: set[uuid.UUID | None] = {root}
    stack = [root]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def browse(
    db: Session, owner: User, at: datetime, folder_id: uuid.UUID | None
) -> tuple[Folder | None, list[Folder], list[PastFile]]:
    """One folder as it was at `at`: its folders (that already existed) and its files."""
    at = _aware(at)
    folder = _owned_folder(db, owner, folder_id)
    subfolders = [
        f
        for f in db.execute(
            select(Folder)
            .where(Folder.owner_id == owner.id, Folder.parent_id == folder_id)
            .order_by(Folder.name)
        ).scalars()
        if _aware(f.created_at) <= at
    ]
    files = list(
        db.execute(
            select(File)
            .where(File.owner_id == owner.id, File.folder_id == folder_id)
            .order_by(File.name)
        ).scalars()
    )
    versions = _versions_by_file(db, [f.id for f in files])
    past: list[PastFile] = []
    for file in files:
        old = _as_of(file, versions.get(file.id, []), at)
        if old is None:
            continue
        past.append(
            PastFile(
                file=file,
                version=old,
                changed=old.content_hash != file.content_hash,
                trashed=file.deleted_at is not None,
            )
        )
    return folder, subfolders, past


def _restore_one(db: Session, owner: User, past: PastFile, report: RestoreReport) -> None:
    file, old = past.file, past.version
    touched = False
    if file.deleted_at is not None:
        trash_service.restore_file(db, owner, file.id)  # commits; name clashes handled there
        db.refresh(file)
        report.undeleted += 1
        touched = True
    if file.content_hash != old.content_hash:
        version_service.restore_version(db, file, old.id, owner)  # a NEW version; commits
        report.restored_content += 1
        touched = True
    if touched:
        if len(report.files) < 200:
            report.files.append(file.name)
    else:
        report.unchanged += 1


def restore_file(db: Session, owner: User, file_id: uuid.UUID, at: datetime) -> RestoreReport:
    at = _aware(at)
    file = db.get(File, file_id)
    if file is None or file.owner_id != owner.id:
        raise NotFoundError("file not found")
    versions = _versions_by_file(db, [file.id]).get(file.id, [])
    old = _as_of(file, versions, at)
    if old is None:
        raise NotFoundError("that file did not exist at that time")
    report = RestoreReport()
    _restore_one(
        db, owner, PastFile(file, old, old.content_hash != file.content_hash, False), report
    )
    activity_service.record(
        db, owner.id, "rewound", file_id=file.id, file_name=file.name, detail=f"to {at.isoformat()}"
    )
    db.commit()
    return report


def restore_tree(
    db: Session, owner: User, at: datetime, folder_id: uuid.UUID | None, *, dry_run: bool
) -> RestoreReport:
    """Put every file under `folder_id` (or everything) back to how it was at `at`."""
    at = _aware(at)
    folder = _owned_folder(db, owner, folder_id)
    scope = _subtree_folder_ids(db, owner, folder_id)
    files = [
        f
        for f in db.execute(select(File).where(File.owner_id == owner.id)).scalars()
        if f.folder_id in scope
    ]
    versions = _versions_by_file(db, [f.id for f in files])
    report = RestoreReport()
    for file in files:
        old = _as_of(file, versions.get(file.id, []), at)
        if old is None:
            if file.deleted_at is None and versions.get(file.id):
                report.newer_untouched += 1  # made after the chosen time: never touched
            continue
        past = PastFile(
            file, old, old.content_hash != file.content_hash, file.deleted_at is not None
        )
        if dry_run:
            if past.trashed:
                report.undeleted += 1
            if past.changed:
                report.restored_content += 1
            if not past.trashed and not past.changed:
                report.unchanged += 1
            if (past.trashed or past.changed) and len(report.files) < 200:
                report.files.append(file.name)
        else:
            _restore_one(db, owner, past, report)
    if not dry_run:
        label = folder.name if folder else "all files"
        activity_service.record(
            db,
            owner.id,
            "rewound",
            file_id=None,
            file_name=label,
            detail=(
                f"{report.restored_content} restored, {report.undeleted} undeleted, "
                f"to {at.isoformat()}"
            ),
        )
        db.commit()
    return report
