import hashlib
import os
import sys

import pytest

from cloudsync.database import Entry, StateDB
from cloudsync.scanner import scan


@pytest.fixture
def db(tmp_path):
    database = StateDB(tmp_path / "state.db")
    yield database
    database.close()


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "sync"
    folder.mkdir()
    return folder


def _old(path, content: bytes):
    """Create a file that looks like it was written long ago (so it counts as settled)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    long_ago = path.stat().st_mtime - 3600
    os.utime(path, (long_ago, long_ago))
    return path


def test_finds_files_and_folders_with_relative_posix_paths(root, db) -> None:
    _old(root / "top.txt", b"top")
    _old(root / "docs" / "deep" / "a.pdf", b"pdf")
    (root / "empty").mkdir()

    result = scan(root, db)

    assert set(result.files) == {"top.txt", "docs/deep/a.pdf"}
    assert result.dirs == {"docs", "docs/deep", "empty"}
    assert result.files["top.txt"].content_hash == hashlib.sha256(b"top").hexdigest()
    assert result.files["top.txt"].size == 3


def test_internal_and_ignored_files_are_skipped(root, db) -> None:
    _old(root / ".cloudsync" / "state.db", b"x")
    _old(root / ".DS_Store", b"x")
    _old(root / "notes.swp", b"x")
    _old(root / "real.txt", b"x")

    assert set(scan(root, db).files) == {"real.txt"}


def test_recently_modified_files_are_unstable_and_not_hashed(root, db) -> None:
    fresh = root / "being-written.bin"
    fresh.write_bytes(b"partial")  # mtime = now
    hashed = []

    result = scan(root, db, settle_seconds=60, hash_file=lambda p: hashed.append(p) or "h")

    assert result.unstable == {"being-written.bin"}
    assert "being-written.bin" not in result.files
    assert hashed == []


def test_a_file_dated_in_the_future_is_still_synced(root, db) -> None:
    path = root / "skewed-camera.jpg"
    path.write_bytes(b"photo")
    future = path.stat().st_mtime + 10 * 24 * 3600
    os.utime(path, (future, future))

    result = scan(root, db, settle_seconds=60)

    assert "skewed-camera.jpg" in result.files and not result.unstable


def test_unchanged_files_are_not_rehashed(root, db) -> None:
    path = _old(root / "big.bin", b"original")
    first = scan(root, db).files["big.bin"]
    db.put_entry(Entry("big.bin", "f1", first.content_hash, "v1", first.size, first.mtime_ns))
    calls = []

    again = scan(root, db, hash_file=lambda p: calls.append(p) or "SHOULD-NOT-BE-USED")

    assert calls == []
    assert again.files["big.bin"].content_hash == first.content_hash
    assert path.exists()


def test_a_changed_file_is_rehashed(root, db) -> None:
    path = _old(root / "doc.txt", b"before")
    before = scan(root, db).files["doc.txt"]
    db.put_entry(Entry("doc.txt", "f1", before.content_hash, "v1", before.size, before.mtime_ns))
    _old(path, b"after, and longer")

    after = scan(root, db).files["doc.txt"]

    assert after.content_hash == hashlib.sha256(b"after, and longer").hexdigest()


def test_a_file_modified_while_being_hashed_is_unstable(root, db) -> None:
    path = _old(root / "busy.bin", b"v1")

    def hash_then_modify(p):
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        p.write_bytes(b"changed during the read")  # a writer got in
        return digest

    result = scan(root, db, hash_file=hash_then_modify)

    assert result.unstable == {"busy.bin"} and "busy.bin" not in result.files
    assert path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="creating symlinks needs privileges on Windows")
def test_symlinks_are_never_followed(root, db, tmp_path) -> None:
    outside = tmp_path / "outside"
    _old(outside / "secret.txt", b"secret")
    os.symlink(outside, root / "link-to-dir")
    os.symlink(outside / "secret.txt", root / "link-to-file")
    _old(root / "real.txt", b"ok")

    result = scan(root, db)

    assert set(result.files) == {"real.txt"}
    assert result.dirs == set()


def test_unsyncable_names_are_reported_not_fatal(root, db, monkeypatch) -> None:
    monkeypatch.setattr(
        "cloudsync.scanner.name_problem", lambda n: "bad" if n.startswith("unsyncable") else None
    )
    _old(root / "unsyncable.txt", b"x")
    _old(root / "fine.txt", b"x")

    result = scan(root, db)

    assert set(result.files) == {"fine.txt"}
    assert result.problems == {"unsyncable.txt": "bad"}


def test_an_empty_folder_scans_clean(root, db) -> None:
    result = scan(root, db)

    assert (result.files, result.dirs, result.unstable, result.problems) == ({}, set(), set(), {})
