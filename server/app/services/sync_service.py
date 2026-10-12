"""Helpers for sync clients (desktop now, phone later): snapshot + folder paths.

A sync client works in terms of *paths* ("Research/paper.pdf"), while the rest
of the API works in terms of ids and a folder tree. This module is the bridge:

- `build_snapshot` returns the owner's whole live tree as flat lists with the
  full path of every folder and file, in two queries, so a client can compare
  it against its local state in one round trip instead of walking the tree.
- `ensure_folder_path` creates a nested folder path if it doesn't exist yet and
  is a no-op if it does, so a client can upload `a/b/c/file.txt` without
  creating `a`, `a/b` and `a/b/c` one request at a time.

Trashed files are not in the snapshot: to a sync client a file in the trash is
a deleted file. (They stay recoverable on the server.)
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.folder import Folder
from app.models.user import User
from app.services.errors import ValidationError
from app.services.file_service import _validate_filename

MAX_PATH_DEPTH = 64


@dataclass(frozen=True)
class SnapshotFolder:
    id: uuid.UUID
    parent_id: uuid.UUID | None
    path: str


@dataclass(frozen=True)
class SnapshotFile:
    id: uuid.UUID
    folder_id: uuid.UUID | None
    name: str
    path: str
    size: int
    content_hash: str | None
    version_id: uuid.UUID | None
    updated_at: datetime


@dataclass(frozen=True)
class Snapshot:
    folders: list[SnapshotFolder]
    files: list[SnapshotFile]


def _folder_paths(folders: list[Folder]) -> dict[uuid.UUID, str]:
    """Maps every folder id to its '/'-joined path from the root."""
    by_id = {f.id: f for f in folders}
    paths: dict[uuid.UUID, str] = {}

    def resolve(folder_id: uuid.UUID) -> str:
        if folder_id in paths:
            return paths[folder_id]
        parts: list[str] = []
        seen: set[uuid.UUID] = set()
        current: uuid.UUID | None = folder_id
        while current is not None and current in by_id and current not in seen:
            seen.add(current)
            parts.append(by_id[current].name)
            current = by_id[current].parent_id
        # Reversed: leaf-first -> root-first. (A cycle can't be created through
        # the API, but a corrupt row must not make this loop forever.)
        path = "/".join(reversed(parts))
        paths[folder_id] = path
        return path

    for folder in folders:
        resolve(folder.id)
    return paths


def build_snapshot(db: Session, owner: User) -> Snapshot:
    folders = list(
        db.execute(select(Folder).where(Folder.owner_id == owner.id).order_by(Folder.name))
        .scalars()
        .all()
    )
    files = list(
        db.execute(
            select(File)
            .where(File.owner_id == owner.id, File.deleted_at.is_(None))
            .order_by(File.name)
        )
        .scalars()
        .all()
    )
    paths = _folder_paths(folders)

    snapshot_folders = sorted(
        (SnapshotFolder(id=f.id, parent_id=f.parent_id, path=paths[f.id]) for f in folders),
        key=lambda f: f.path,
    )
    snapshot_files = []
    for f in files:
        prefix = paths.get(f.folder_id, "") if f.folder_id is not None else ""
        snapshot_files.append(
            SnapshotFile(
                id=f.id,
                folder_id=f.folder_id,
                name=f.name,
                path=f"{prefix}/{f.name}" if prefix else f.name,
                size=f.size,
                content_hash=f.content_hash,
                version_id=f.current_version_id,
                updated_at=f.updated_at,
            )
        )
    snapshot_files.sort(key=lambda f: f.path)
    return Snapshot(folders=snapshot_folders, files=snapshot_files)


def snapshot_etag(snapshot: Snapshot) -> str:
    """A fingerprint of everything a sync client can observe in `snapshot`.

    Derived from the content itself (ids, paths, versions, hashes), not from
    timestamps, so it changes exactly when the snapshot would: an upload, edit,
    rename, move, delete, restore or new folder all change it, and nothing else
    does. A client that sends it back as `If-None-Match` gets a bodyless `304`
    instead of re-downloading an unchanged tree.

    The records are JSON-encoded before hashing so a file name containing a
    separator character can never make two different trees hash alike.
    """
    records = [["d", str(f.id), str(f.parent_id), f.path] for f in snapshot.folders] + [
        [
            "f",
            str(f.id),
            str(f.folder_id),
            f.path,
            f.size,
            f.content_hash,
            str(f.version_id),
        ]
        for f in snapshot.files
    ]
    encoded = json.dumps(records, separators=(",", ":"), ensure_ascii=True)
    return '"' + hashlib.sha256(encoded.encode("ascii")).hexdigest() + '"'


def etag_matches(header: str | None, etag: str) -> bool:
    """Whether an `If-None-Match` header value matches `etag` (weak validators and `*` included)."""
    if not header:
        return False
    if header.strip() == "*":
        return True
    candidates = [part.strip() for part in header.split(",")]
    return any(c.removeprefix("W/") == etag for c in candidates)


def split_path(path: str) -> list[str]:
    """Validates and splits a client-supplied relative path into components.

    Rejects anything that could escape the owner's tree or isn't a legal
    name (`..`, backslashes, empty components other than from a leading or
    trailing slash, null bytes). Raises `ValidationError`.
    """
    components = [c for c in path.split("/") if c != ""]
    if len(components) > MAX_PATH_DEPTH:
        raise ValidationError(f"path is more than {MAX_PATH_DEPTH} folders deep")
    return [_validate_filename(c) for c in components]


def ensure_folder_path(db: Session, owner: User, path: str) -> Folder | None:
    """Returns the folder at `path`, creating any missing folders on the way.

    `None` means the root (an empty path). Idempotent. Commits only if it had
    to create something.
    """
    parent_id: uuid.UUID | None = None
    folder: Folder | None = None
    created = False

    for name in split_path(path):
        folder = (
            db.execute(
                select(Folder)
                .where(
                    Folder.owner_id == owner.id,
                    Folder.parent_id == parent_id,
                    Folder.name == name,
                )
                .order_by(Folder.created_at, Folder.id)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if folder is None:
            folder = Folder(id=uuid.uuid4(), owner_id=owner.id, parent_id=parent_id, name=name)
            db.add(folder)
            db.flush()
            created = True
        parent_id = folder.id

    if created:
        db.commit()
    return folder
