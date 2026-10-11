"""Scan the sync folder: what is on disk right now.

Hashing every file on every cycle would make sync unusable on a large folder,
so a file is only re-hashed when its size or modification time differs from
what the state database recorded at the last sync. Files that were modified
very recently are reported as `unstable` and left out of the cycle: they are
probably still being written (a download, an editor save, a copy in progress),
and uploading half a file would create a bad version.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .database import StateDB
from .hasher import sha256_file
from .paths import INTERNAL_DIR, is_ignored_name, name_problem


@dataclass(frozen=True)
class LocalFile:
    path: str  # relative, '/'-separated
    size: int
    mtime_ns: int
    content_hash: str


@dataclass
class ScanResult:
    files: dict[str, LocalFile] = field(default_factory=dict)
    dirs: set[str] = field(default_factory=set)
    # Modified too recently to trust: skip this cycle, change nothing about them.
    unstable: set[str] = field(default_factory=set)
    # Cannot be synced from this machine (e.g. illegal name on Windows): path -> reason.
    problems: dict[str, str] = field(default_factory=dict)


def scan(
    root: Path,
    db: StateDB,
    *,
    settle_seconds: float = 2.0,
    now: Callable[[], float] = time.time,
    hash_file: Callable[[Path], str] = sha256_file,
) -> ScanResult:
    result = ScanResult()
    known = db.all_entries()
    current_time = now()

    def walk(directory: Path, prefix: str) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return  # unreadable directory: leave it alone rather than treating its files as deleted
        for entry in sorted(entries, key=lambda e: e.name):
            name = entry.name
            if name == INTERNAL_DIR or is_ignored_name(name):
                continue
            rel = f"{prefix}{name}"
            if entry.is_symlink():
                # Following links could escape the folder or loop; never sync them.
                continue
            problem = name_problem(name)
            if problem:
                result.problems[rel] = problem
                continue
            if entry.is_dir(follow_symlinks=False):
                result.dirs.add(rel)
                walk(Path(entry.path), rel + "/")
            elif entry.is_file(follow_symlinks=False):
                _scan_file(rel, Path(entry.path))

    def _scan_file(rel: str, path: Path) -> None:
        try:
            stat = path.stat()
        except OSError:
            result.unstable.add(rel)
            return
        age = current_time - stat.st_mtime
        # Only a file modified moments ago is "probably still being written". A
        # modification time in the future (clock-skewed camera, archive extracted
        # with preserved timestamps) says nothing about recency, so such a file
        # must not be held back forever; the before/after stat check below still
        # catches a genuine write in progress.
        if 0 <= age < settle_seconds:
            result.unstable.add(rel)
            return

        cached = known.get(rel)
        if cached and cached.size == stat.st_size and cached.mtime_ns == stat.st_mtime_ns:
            digest = cached.content_hash  # unchanged since the last sync: no need to read it
        else:
            try:
                digest = hash_file(path)
                after = path.stat()
            except OSError:
                result.unstable.add(rel)
                return
            if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                # Changed while we were reading it.
                result.unstable.add(rel)
                return
        result.files[rel] = LocalFile(rel, stat.st_size, stat.st_mtime_ns, digest)

    walk(root, "")
    return result
