import os
import sys

import pytest

from cloudsync.paths import (
    INTERNAL_DIR,
    UnsafePathError,
    is_ignored,
    name_problem,
    path_problem,
    safe_join,
    split_parent,
    to_rel,
)


@pytest.mark.parametrize(
    "path",
    [
        ".DS_Store",
        "docs/Thumbs.db",
        "a/b/~$budget.xlsx",
        ".~lock.report.odt#",
        "notes.txt.swp",
        "video.mp4.part",
        "download.crdownload",
        "x/.#emacs-lock",
        f"{INTERNAL_DIR}/state.db",
        f"deep/{INTERNAL_DIR}/tmp/file",
        "scratch.tmp",
    ],
)
def test_ignored_paths(path: str) -> None:
    assert is_ignored(path)


@pytest.mark.parametrize("path", ["notes.txt", "a/b/c.pdf", "tmp/readme", "my.tmpfile", ".bashrc"])
def test_normal_paths_are_not_ignored(path: str) -> None:
    assert not is_ignored(path)


def test_linux_allows_names_windows_would_reject() -> None:
    assert name_problem("report: final?.txt", windows=False) is None


@pytest.mark.parametrize(
    "name",
    [
        "report: final.txt",
        "what?.txt",
        "a|b",
        'say "hi".txt',
        "trailing.",
        "trailing ",
        "CON",
        "nul.txt",
        "COM3.log",
        "bell\x07",
    ],
)
def test_windows_rejects_illegal_names(name: str) -> None:
    assert name_problem(name, windows=True) is not None


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "a\x00b"])
def test_separators_and_relative_names_are_rejected_everywhere(name: str) -> None:
    assert name_problem(name, windows=False) is not None


def test_path_problem_names_the_offending_component() -> None:
    assert "bad:name" in path_problem("ok/bad:name/file.txt", windows=True)
    assert path_problem("ok/fine/file.txt", windows=True) is None


def test_safe_join_stays_inside_the_root(tmp_path) -> None:
    assert safe_join(tmp_path, "a/b/c.txt") == tmp_path.resolve() / "a" / "b" / "c.txt"


@pytest.mark.parametrize(
    "rel",
    ["../escape.txt", "a/../../escape", "/etc/passwd", "a//b", "a/./b", "", "a\\b", "a/../b"],
)
def test_safe_join_rejects_escapes(tmp_path, rel: str) -> None:
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, rel)


@pytest.mark.skipif(sys.platform == "win32", reason="creating symlinks needs privileges on Windows")
def test_safe_join_rejects_a_symlink_that_points_outside(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "link")

    with pytest.raises(UnsafePathError):
        safe_join(root, "link/stolen.txt")


def test_to_rel_and_split_parent(tmp_path) -> None:
    (tmp_path / "a").mkdir()
    assert to_rel(tmp_path, tmp_path / "a" / "b.txt") == "a/b.txt"
    assert split_parent("a/b/c.txt") == ("a/b", "c.txt")
    assert split_parent("c.txt") == ("", "c.txt")
