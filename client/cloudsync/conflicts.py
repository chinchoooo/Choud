"""Conflict copies (Phase 8): never overwrite either side, keep both.

When a file changed on both sides since it was last in sync, the client keeps
the server's version at the original path and saves the local edit next to it
as `name.conflict-YYYY-MM-DD.ext`. The copy is an ordinary file, so the next
sync uploads it and every device ends up with both versions. No merging: that
is explicitly out of scope (docs/architecture.md, Explicit Non-Goals).
"""

from __future__ import annotations

import datetime as _dt
import posixpath
from collections.abc import Callable


def conflict_path(
    rel_path: str,
    exists: Callable[[str], bool],
    today: _dt.date | None = None,
) -> str:
    """A free sibling path for the conflict copy of `rel_path`.

    `report.pdf` -> `report.conflict-2026-10-17.pdf`, then `...-2.pdf`,
    `...-3.pdf` if those names are taken. `exists` tells whether a relative
    path is already in use (on disk or already planned this cycle).
    """
    day = (today or _dt.date.today()).isoformat()
    directory, name = posixpath.split(rel_path)
    stem, ext = posixpath.splitext(name)
    if not stem:  # a dotfile such as ".bashrc": treat the whole name as the stem
        stem, ext = name, ""

    attempt = 1
    while True:
        suffix = f".conflict-{day}" if attempt == 1 else f".conflict-{day}-{attempt}"
        candidate = posixpath.join(directory, f"{stem}{suffix}{ext}")
        if not exists(candidate):
            return candidate
        attempt += 1


def is_conflict_copy(rel_path: str) -> bool:
    """Whether a path looks like a conflict copy made by this client."""
    return ".conflict-" in posixpath.basename(rel_path)
