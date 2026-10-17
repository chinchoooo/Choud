"""Garbage collection of storage that nothing references (Phase 15).

Normal operation already frees space: purging a trashed file deletes objects only that file used.
What is left are *orphans* from things that went wrong half way: an object stored but the database
write failed, a failed delete, an abandoned upload's chunks, staging copies from a crash. They are
harmless but they take disk, so this finds them and (only when asked) removes them.

Safety rules (the project's "never silently destroy data"):

- An object is an orphan only if **no** file and **no** file version, of any user, names its hash.
  Trashed files still have rows, so their bytes are never touched.
- Anything younger than the grace period is left alone: an upload stores the bytes *before* its
  database row is committed, and that window must never be mistaken for an orphan.
- The reference check is repeated for each object right before it is deleted.
- Objects are deleted through the storage engine, never by unlinking files here. This module only
  *reads* the storage volume to see what exists (the engine has no list call, and the engine API is
  kept small on purpose).
- Without `delete=True` nothing is removed: the report says what would be.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion
from app.models.upload import Upload
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

_OBJECT_NAME = re.compile(r"^[0-9a-f]{64}$")
_THUMB_NAME = re.compile(r"^([0-9a-f]{64})-\d+\.jpg$")
_UUID_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

STAGING_MAX_AGE_SECONDS = 24 * 3600


@dataclass
class GcReport:
    dry_run: bool
    grace_seconds: float
    objects_scanned: int = 0
    orphan_objects: int = 0
    orphan_bytes: int = 0
    removed_objects: int = 0
    removed_bytes: int = 0
    orphan_thumbnails: int = 0
    removed_thumbnails: int = 0
    stale_staging_files: int = 0
    removed_staging_files: int = 0
    orphan_upload_dirs: int = 0
    removed_upload_dirs: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        verb = "would remove" if self.dry_run else "removed"
        objects = self.orphan_objects if self.dry_run else self.removed_objects
        size = self.orphan_bytes if self.dry_run else self.removed_bytes
        thumbs = self.orphan_thumbnails if self.dry_run else self.removed_thumbnails
        staging = self.stale_staging_files if self.dry_run else self.removed_staging_files
        dirs = self.orphan_upload_dirs if self.dry_run else self.removed_upload_dirs
        text = (
            f"gc ({'dry run' if self.dry_run else 'deleting'}): scanned {self.objects_scanned} "
            f"object(s); {verb} {objects} orphan object(s) ({size} bytes), {thumbs} thumbnail(s), "
            f"{staging} stale staging file(s), {dirs} abandoned upload folder(s)"
        )
        if self.errors:
            text += f"; {len(self.errors)} problem(s): {self.errors[0]}"
        return text


def _referenced_hashes(db: Session) -> set[str]:
    versions = db.scalars(select(FileVersion.content_hash).distinct())
    files = db.scalars(select(File.content_hash).where(File.content_hash.is_not(None)).distinct())
    return {h for h in versions if h} | {h for h in files if h}


def _still_referenced(db: Session, content_hash: str) -> bool:
    in_versions = db.scalar(select(exists().where(FileVersion.content_hash == content_hash)))
    in_files = db.scalar(select(exists().where(File.content_hash == content_hash)))
    return bool(in_versions or in_files)


def _is_old_enough(path: Path, now: float, grace: float) -> bool:
    try:
        return now - path.stat().st_mtime >= grace
    except OSError:
        return False  # vanished or unreadable: leave it


def run_gc(
    db: Session,
    storage: StorageService,
    storage_root: Path,
    *,
    delete: bool = False,
    grace_hours: float = 72.0,
    now: float | None = None,
) -> GcReport:
    """Finds (and with `delete=True`, removes) unreferenced storage. See the module docstring."""
    now = time.time() if now is None else now
    grace = max(grace_hours, 0.0) * 3600
    report = GcReport(dry_run=not delete, grace_seconds=grace)

    # If the database cannot be read there is no way to know what is referenced: do nothing.
    referenced = _referenced_hashes(db)

    _collect_objects(db, storage, storage_root / "objects", referenced, report, now, grace, delete)
    _collect_thumbnails(storage_root / "thumbs", referenced, report, now, grace, delete)
    _collect_staging(storage_root / "staging", report, now, delete)
    _collect_upload_dirs(db, storage, storage_root / "uploads", report, now, grace, delete)

    logger.info(report.summary())
    return report


def _collect_objects(
    db, storage, objects_dir: Path, referenced, report, now, grace, delete
) -> None:
    if not objects_dir.is_dir():
        return
    for shard in sorted(objects_dir.iterdir()):
        if shard.is_symlink() or not shard.is_dir() or len(shard.name) != 2:
            continue
        for entry in sorted(shard.iterdir()):
            if entry.is_symlink() or not entry.is_file():
                continue
            name = entry.name
            if not _OBJECT_NAME.match(name) or name[:2] != shard.name:
                continue  # not one of ours (a temp file, a stray): never touch it
            report.objects_scanned += 1
            if name in referenced or not _is_old_enough(entry, now, grace):
                continue
            size = entry.stat().st_size
            report.orphan_objects += 1
            report.orphan_bytes += size
            if not delete:
                continue
            if _still_referenced(db, name):
                # a row appeared since the scan began: it is no longer an orphan
                report.orphan_objects -= 1
                report.orphan_bytes -= size
                continue
            try:
                if storage.remove(name):
                    report.removed_objects += 1
                    report.removed_bytes += size
            except Exception as exc:  # engine down, etc.: report it and keep the bytes
                report.errors.append(f"could not delete object {name[:12]}: {exc}")


def _collect_thumbnails(thumbs_dir: Path, referenced, report, now, grace, delete) -> None:
    """Thumbnails are derived data named after their source's hash; unreferenced ones go."""
    if not thumbs_dir.is_dir():
        return
    for entry in thumbs_dir.iterdir():
        match = _THUMB_NAME.match(entry.name)
        if entry.is_symlink() or not entry.is_file() or not match:
            continue
        if match.group(1) in referenced or not _is_old_enough(entry, now, grace):
            continue
        report.orphan_thumbnails += 1
        if delete:
            try:
                entry.unlink()
                report.removed_thumbnails += 1
            except OSError as exc:
                report.errors.append(f"could not delete thumbnail {entry.name[:12]}: {exc}")


def _collect_staging(staging_dir: Path, report, now, delete) -> None:
    """Staging holds copies for in-flight requests; anything a day old is a crash leftover."""
    if not staging_dir.is_dir():
        return
    for entry in staging_dir.iterdir():
        if entry.is_symlink() or not entry.is_file():
            continue
        if not _is_old_enough(entry, now, STAGING_MAX_AGE_SECONDS):
            continue
        report.stale_staging_files += 1
        if delete:
            try:
                entry.unlink()
                report.removed_staging_files += 1
            except OSError as exc:
                report.errors.append(f"could not delete staging file {entry.name[:12]}: {exc}")


def _collect_upload_dirs(db, storage, uploads_dir: Path, report, now, grace, delete) -> None:
    """Chunk folders whose upload session no longer exists (the sweep removes sessions first)."""
    if not uploads_dir.is_dir():
        return
    for entry in uploads_dir.iterdir():
        if entry.is_symlink() or not entry.is_dir() or not _UUID_NAME.match(entry.name):
            continue
        if not _is_old_enough(entry, now, grace):
            continue
        if db.scalar(select(exists().where(Upload.id == uuid.UUID(entry.name)))):
            continue  # a live or recent session still owns it
        report.orphan_upload_dirs += 1
        if delete:
            try:
                storage.abandon_upload(entry.name)
                report.removed_upload_dirs += 1
            except Exception as exc:
                report.errors.append(f"could not remove upload folder {entry.name[:8]}: {exc}")
