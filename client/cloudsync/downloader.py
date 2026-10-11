"""Bring server content to disk safely: staged, verified, then swapped in atomically.

A download never writes to the destination until it is complete and its hash
matches what the server's snapshot promised. A crash, a dropped connection or
a file that changed mid-transfer therefore leaves the old local file untouched
instead of a truncated or corrupt one (Rule 5).
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .api import ApiClient, RemoteFile
from .paths import safe_join


class ChangedDuringTransfer(Exception):
    """The bytes received do not match the snapshot: the file changed meanwhile."""


@dataclass(frozen=True)
class Downloaded:
    content_hash: str
    size: int
    mtime_ns: int


def download_file(
    api: ApiClient, root: Path, rel_path: str, remote: RemoteFile, state_dir: Path
) -> Downloaded:
    target = safe_join(root, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = state_dir / "tmp"
    staging.mkdir(parents=True, exist_ok=True)
    part = staging / f"{uuid.uuid4().hex}.part"
    try:
        digest, size = api.download(remote.id, part)
        if remote.content_hash and digest != remote.content_hash:
            # Someone saved a new version between the snapshot and the download.
            # Nothing is replaced; the next cycle sees the new snapshot.
            raise ChangedDuringTransfer(f"{rel_path} changed on the server during download")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return Downloaded(digest, size, target.stat().st_mtime_ns)


def move_to_local_trash(root: Path, rel_path: str, state_dir: Path) -> Path:
    """Move a file into `.cloudsync/trash/<timestamp>/<path>` instead of deleting it.

    Used when the server deleted a file: the copy on disk is recoverable until
    the user empties the folder themselves.
    """
    source = safe_join(root, rel_path)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    destination = state_dir / "trash" / stamp / rel_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination = destination.with_name(f"{destination.name}.{uuid.uuid4().hex[:8]}")
    os.replace(source, destination)
    return destination
