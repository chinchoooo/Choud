import datetime as dt
import hashlib

from cloudsync.conflicts import conflict_path, is_conflict_copy
from cloudsync.hasher import sha256_file

DAY = dt.date(2026, 10, 17)


def test_conflict_name_keeps_the_extension() -> None:
    assert conflict_path("report.pdf", lambda p: False, DAY) == "report.conflict-2026-10-17.pdf"


def test_conflict_name_in_a_subfolder_and_with_multiple_dots() -> None:
    assert (
        conflict_path("a/b/archive.tar.gz", lambda p: False, DAY)
        == "a/b/archive.tar.conflict-2026-10-17.gz"
    )


def test_conflict_name_without_an_extension_and_for_dotfiles() -> None:
    assert conflict_path("Makefile", lambda p: False, DAY) == "Makefile.conflict-2026-10-17"
    assert conflict_path(".bashrc", lambda p: False, DAY) == ".bashrc.conflict-2026-10-17"


def test_a_taken_conflict_name_gets_a_counter() -> None:
    taken = {"r.conflict-2026-10-17.txt", "r.conflict-2026-10-17-2.txt"}

    assert conflict_path("r.txt", taken.__contains__, DAY) == "r.conflict-2026-10-17-3.txt"


def test_is_conflict_copy() -> None:
    assert is_conflict_copy("a/r.conflict-2026-10-17.txt")
    assert not is_conflict_copy("a/r.txt")


def test_sha256_matches_hashlib_for_empty_small_and_multi_block_files(tmp_path) -> None:
    for name, data in [
        ("empty", b""),
        ("small", b"hello"),
        ("big", bytes(range(256)) * 20_000),  # ~5 MB: several 1 MiB blocks
    ]:
        path = tmp_path / name
        path.write_bytes(data)
        assert sha256_file(path) == hashlib.sha256(data).hexdigest()
