"""Path handling: what to ignore, what names are legal here, and escaping safely.

Everything the client does to the local disk goes through `safe_join`, so a
hostile or buggy server cannot make it write outside the sync folder with a
name like `../../.ssh/authorized_keys`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# The client's private directory inside the sync folder: state database,
# download staging area, local trash. Never synced.
INTERNAL_DIR = ".cloudsync"

IGNORED_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", "Icon\r", INTERNAL_DIR})
IGNORED_SUFFIXES = (".tmp", ".part", ".crdownload", ".swp", ".swx", ".swo")
IGNORED_PREFIXES = ("~$", ".~lock.", ".#")

_WINDOWS_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class UnsafePathError(ValueError):
    """A server-supplied path would escape the sync folder or is otherwise unusable."""


def is_ignored_name(name: str) -> bool:
    return (
        name in IGNORED_NAMES
        or name.endswith(IGNORED_SUFFIXES)
        or name.startswith(IGNORED_PREFIXES)
    )


def is_ignored(rel_path: str) -> bool:
    """True if any component of the relative path is something we never sync."""
    return any(is_ignored_name(part) for part in rel_path.split("/") if part)


def name_problem(name: str, *, windows: bool | None = None) -> str | None:
    """Why `name` cannot be created on this machine, or None if it can.

    A file called `report: final?.txt` is legal on a Linux server but cannot
    exist on Windows. Such files are skipped (and reported) instead of failing
    the whole sync. The Windows rules only apply when running on Windows.
    """
    if name in ("", ".", ".."):
        return "empty or relative name"
    if "/" in name or "\\" in name or "\x00" in name:
        return "contains a path separator or null byte"
    if windows is None:
        windows = sys.platform == "win32"
    if not windows:
        return None
    if _WINDOWS_BAD_CHARS.search(name):
        return "contains a character Windows does not allow"
    if name.endswith((" ", ".")):
        return "ends with a space or dot, which Windows does not allow"
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        return "is a reserved device name on Windows"
    return None


def path_problem(rel_path: str, *, windows: bool | None = None) -> str | None:
    """`name_problem` for every component of a relative path."""
    for part in rel_path.split("/"):
        problem = name_problem(part, windows=windows)
        if problem:
            return f"{part!r} {problem}"
    return None


def safe_join(root: Path, rel_path: str) -> Path:
    """`root / rel_path`, guaranteed to stay inside `root`.

    Raises `UnsafePathError` for absolute paths, `..` components, or anything
    that resolves (through symlinks) outside the root.
    """
    if not rel_path or rel_path.startswith("/") or "\\" in rel_path:
        raise UnsafePathError(f"not a relative sync path: {rel_path!r}")
    parts = rel_path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise UnsafePathError(f"path has an empty or relative component: {rel_path!r}")
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*parts)
    # resolve() follows symlinks that already exist, so a planted link out of
    # the folder is caught here too.
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafePathError(f"path escapes the sync folder: {rel_path!r}") from exc
    return candidate


def to_rel(root: Path, path: Path) -> str:
    """Relative posix path of `path` under `root` (always '/'-separated)."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def split_parent(rel_path: str) -> tuple[str, str]:
    """`"a/b/c.txt"` -> `("a/b", "c.txt")`; a root file has parent `""`."""
    parent, _, name = rel_path.rpartition("/")
    return parent, name
