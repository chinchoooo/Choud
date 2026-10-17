"""Space insights: where the bytes went, what deduplication saved, what old versions cost (a Choud
original). Everything is computed from the database for one user; nothing here touches the disk
except the optional, explicit version pruning at the end.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion
from app.models.user import User
from app.services import activity_service, trash_service
from app.services.storage_service import get_storage_service

_CATEGORIES = (
    ("Photos", ("image/",)),
    ("Videos", ("video/",)),
    ("Audio", ("audio/",)),
    (
        "Documents",
        ("application/pdf", "text/", "application/msword", "application/vnd.", "application/rtf"),
    ),
    ("Archives", ("application/zip", "application/x-", "application/gzip", "application/vnd.rar")),
)


def category(mime: str | None) -> str:
    mime = (mime or "").lower()
    for label, prefixes in _CATEGORIES:
        if mime.startswith(prefixes):
            return label
    return "Other"


@dataclass
class SpaceReport:
    logical_bytes: int = 0  # every version of every file, counted in full
    stored_bytes: int = 0  # the same, with identical content counted once
    dedup_saved_bytes: int = 0
    current_bytes: int = 0  # the live files as they are now
    trash_bytes: int = 0
    history_bytes: int = 0  # held only by old versions (what pruning could give back)
    by_type: dict[str, int] = field(default_factory=dict)
    biggest: list[dict] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    duplicate_files: int = 0


def _rows(db: Session, user: User):
    return db.execute(
        select(
            FileVersion.file_id,
            FileVersion.id,
            FileVersion.content_hash,
            FileVersion.size,
            FileVersion.version_number,
            File.name,
            File.mime_type,
            File.current_version_id,
            File.content_hash.label("current_hash"),
            File.size.label("current_size"),
            File.deleted_at,
        )
        .join(File, File.id == FileVersion.file_id)
        .where(File.owner_id == user.id)
    ).all()


def space_report(db: Session, user: User) -> SpaceReport:
    rows = _rows(db, user)
    report = SpaceReport()
    first_size: dict[str, int] = {}
    current_hashes: set[str] = set()
    live: dict[uuid.UUID, tuple] = {}
    for row in rows:
        report.logical_bytes += row.size
        first_size.setdefault(row.content_hash, row.size)
        if row.id == row.current_version_id:
            current_hashes.add(row.content_hash)
            if row.deleted_at is None:
                live[row.file_id] = row
                report.current_bytes += row.size
            else:
                report.trash_bytes += row.size
    report.stored_bytes = sum(first_size.values())
    report.dedup_saved_bytes = report.logical_bytes - report.stored_bytes
    report.history_bytes = sum(
        size for content_hash, size in first_size.items() if content_hash not in current_hashes
    )

    by_type: dict[str, int] = defaultdict(int)
    for row in live.values():
        by_type[category(row.mime_type)] += row.size
    report.by_type = dict(sorted(by_type.items(), key=lambda item: -item[1]))

    ranked = sorted(live.values(), key=lambda r: -r.size)[:10]
    report.biggest = [{"id": r.file_id, "name": r.name, "size": r.size} for r in ranked]

    groups: dict[str, list] = defaultdict(list)
    for row in live.values():
        groups[row.content_hash].append(row)
    duplicates = [rows_ for rows_ in groups.values() if len(rows_) > 1 and rows_[0].size > 0]
    duplicates.sort(key=lambda g: -(g[0].size * (len(g) - 1)))
    report.duplicate_files = sum(len(g) - 1 for g in duplicates)
    report.duplicates = [
        {
            "size": g[0].size,
            "copies": len(g),
            "files": [{"id": r.file_id, "name": r.name} for r in g[:10]],
        }
        for g in duplicates[:20]
    ]
    return report


@dataclass
class PruneReport:
    versions_removed: int = 0
    bytes_freed: int = 0  # what the removed objects occupied on disk
    files_affected: int = 0


def prune_versions(db: Session, user: User, keep: int, *, dry_run: bool) -> PruneReport:
    """Delete all but the newest `keep` versions of every file. The current version is never
    deleted; an object is removed from disk only if nothing else (any user) still uses it."""
    versions: dict[uuid.UUID, list[FileVersion]] = defaultdict(list)
    current: dict[uuid.UUID, uuid.UUID | None] = {}
    for file in db.execute(select(File).where(File.owner_id == user.id)).scalars():
        current[file.id] = file.current_version_id
    for version in db.execute(
        select(FileVersion)
        .where(FileVersion.file_id.in_(list(current) or [uuid.uuid4()]))
        .order_by(FileVersion.file_id, FileVersion.version_number)
    ).scalars():
        versions[version.file_id].append(version)

    doomed: list[FileVersion] = []
    affected = 0
    for file_id, items in versions.items():
        old = [v for v in items[: max(0, len(items) - keep)] if v.id != current.get(file_id)]
        if old:
            affected += 1
            doomed.extend(old)

    report = PruneReport(versions_removed=len(doomed), files_affected=affected)
    doomed_ids = {v.id for v in doomed}
    survivors = {
        v.content_hash for items in versions.values() for v in items if v.id not in doomed_ids
    }
    candidate_hashes = {v.content_hash for v in doomed} - survivors
    freed: dict[str, int] = {}
    for version in doomed:
        if version.content_hash in candidate_hashes:
            freed.setdefault(version.content_hash, version.size)

    if dry_run:
        # Only an estimate: other users or files outside this scan could still share the object.
        report.bytes_freed = sum(freed.values())
        return report

    for version in doomed:
        db.delete(version)
    activity_service.record(
        db,
        user.id,
        "pruned",
        file_id=None,
        file_name="old versions",
        detail=f"kept the newest {keep}; removed {len(doomed)}",
    )
    db.commit()

    storage = get_storage_service()
    for content_hash, size in freed.items():
        if trash_service._hash_is_referenced(db, content_hash):  # noqa: SLF001
            continue
        try:
            if storage.remove(content_hash):
                report.bytes_freed += size
        except Exception:  # an object that cannot be removed is simply left for GC
            continue
    return report
