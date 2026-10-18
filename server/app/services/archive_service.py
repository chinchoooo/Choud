"""Download several files and folders at once as a single .zip.

The archive is built in a temporary file on the storage volume, one file at a time (each object is
copied out of the engine, added, and its staging copy deleted straight away), so memory and extra
disk use stay small however big the selection is. Only live files the caller owns are included.
"""

import uuid
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.folder import Folder
from app.models.user import User
from app.services import file_service
from app.services.errors import NotFoundError, PayloadTooLargeError

MAX_ENTRIES = 5000
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
_ALREADY_COMPRESSED = ("image/", "video/", "audio/", "application/zip", "application/gzip")


def _unique(name: str, used: set[str]) -> str:
    if name.lower() not in used:
        used.add(name.lower())
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    else:
        ext = "." + ext
    counter = 2
    while True:
        candidate = f"{stem} ({counter}){ext}"
        if candidate.lower() not in used:
            used.add(candidate.lower())
            return candidate
        counter += 1


def _collect(
    db: Session, owner: User, file_ids: list[uuid.UUID], folder_ids: list[uuid.UUID]
) -> list[tuple[str, File]]:
    entries: list[tuple[str, File]] = []
    top_used: set[str] = set()

    for file_id in dict.fromkeys(file_ids):
        file = file_service.get_file(db, owner, file_id)  # 404 for foreign or trashed files
        entries.append((_unique(file.name, top_used), file))

    for folder_id in dict.fromkeys(folder_ids):
        root = file_service.get_folder(db, owner, folder_id)
        base = _unique(root.name, top_used)
        stack: list[tuple[Folder, str]] = [(root, base)]
        while stack:
            folder, prefix = stack.pop()
            used: set[str] = set()
            files = db.execute(
                select(File)
                .where(
                    File.owner_id == owner.id,
                    File.folder_id == folder.id,
                    File.deleted_at.is_(None),
                )
                .order_by(File.name)
            ).scalars()
            for file in files:
                entries.append((f"{prefix}/{_unique(file.name, used)}", file))
            for child in file_service.list_subfolders(db, owner, folder.id):
                stack.append((child, f"{prefix}/{_unique(child.name, used)}"))
            if len(entries) > MAX_ENTRIES:
                raise PayloadTooLargeError(f"select at most {MAX_ENTRIES} files")
    return entries


def build_zip(
    db: Session, owner: User, file_ids: list[uuid.UUID], folder_ids: list[uuid.UUID]
) -> tuple[Path, int]:
    """Writes the archive and returns (path, number of files). The caller deletes the path."""
    if not file_ids and not folder_ids:
        raise NotFoundError("nothing selected")
    entries = _collect(db, owner, file_ids, folder_ids)
    if len(entries) > MAX_ENTRIES:
        raise PayloadTooLargeError(f"select at most {MAX_ENTRIES} files")
    if sum(file.size or 0 for _, file in entries) > MAX_TOTAL_BYTES:
        raise PayloadTooLargeError("that selection is bigger than 4 GiB: download it in parts")

    target = file_service._staging_path(suffix=".zip")  # noqa: SLF001 - same staging volume
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(target, "w", allowZip64=True) as archive:
            for arcname, file in entries:
                staged = file_service.prepare_download(file)
                try:
                    mime = (file.mime_type or "").lower()
                    method = (
                        zipfile.ZIP_STORED
                        if mime.startswith(_ALREADY_COMPRESSED)
                        else zipfile.ZIP_DEFLATED
                    )
                    archive.write(staged, arcname, compress_type=method)
                finally:
                    staged.unlink(missing_ok=True)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target, len(entries)
