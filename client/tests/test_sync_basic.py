"""Phase 7: the basic two-way mirror, run against the real server."""

import hashlib

from tests.conftest import server_files


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_initial_sync_uploads_a_whole_tree_and_is_then_quiet(server, device) -> None:
    laptop = device("laptop")
    laptop.write("top.txt", "top level")
    laptop.write("Research/2026/paper.pdf", b"%PDF " + bytes(range(200)))
    laptop.write("Research/notes.md", "# notes")
    (laptop.root / "EmptyFolder").mkdir()

    first = laptop.sync()

    assert first.uploaded == 3 and not first.errors
    files = server_files(server)
    assert set(files) == {"top.txt", "Research/2026/paper.pdf", "Research/notes.md"}
    assert files["top.txt"]["hash"] == sha(b"top level")
    snapshot = laptop.api.snapshot()
    assert "EmptyFolder" in snapshot.folders  # empty folders sync too

    second = laptop.sync()  # nothing changed: nothing happens
    assert not second.did_work and not second.errors and second.pending == 0


def test_a_fresh_device_downloads_everything_byte_for_byte(server, device) -> None:
    first = device("first")
    big = bytes(range(256)) * 200  # 51 KB: goes through the chunked path (threshold 10 KB)
    first.write("docs/readme.txt", "hello")
    first.write("docs/deep/er/data.bin", big)
    first.sync()

    second = device("second")
    report = second.sync()

    assert report.downloaded == 2 and not report.errors
    assert second.read("docs/readme.txt") == b"hello"
    assert second.read("docs/deep/er/data.bin") == big
    assert second.tree() == first.tree()
    assert not second.sync().did_work  # and it is quiet afterwards


def test_a_local_edit_becomes_a_new_server_version(server, device) -> None:
    laptop = device()
    laptop.write("doc.txt", "version one")
    laptop.sync()
    before = server_files(server)["doc.txt"]

    laptop.write("doc.txt", "version two, longer")
    report = laptop.sync()

    after = server_files(server)["doc.txt"]
    assert report.uploaded == 1
    assert after["id"] == before["id"]  # same file, not a duplicate
    assert after["version"] != before["version"]
    assert after["hash"] == sha(b"version two, longer")
    versions = laptop.api._send("GET", f"/api/files/{after['id']}/versions").json()["versions"]
    assert len(versions) == 2  # history kept: the old version is still recoverable
    assert not laptop.sync().did_work


def test_a_change_on_another_device_is_downloaded(server, device) -> None:
    a, b = device("a"), device("b")
    a.write("shared.txt", "original")
    a.sync()
    b.sync()

    a.write("shared.txt", "edited on A")
    a.sync()
    report = b.sync()

    assert report.downloaded == 1
    assert b.read("shared.txt") == b"edited on A"
    assert not b.sync().did_work


def test_a_local_delete_moves_the_file_to_the_server_trash(server, device) -> None:
    laptop = device()
    laptop.write("gone.txt", "bye")
    laptop.write("stay.txt", "stay")
    laptop.sync()

    laptop.delete("gone.txt")
    report = laptop.sync()

    assert report.deleted_remote == 1
    assert set(server_files(server)) == {"stay.txt"}
    trash = laptop.api._send("GET", "/api/trash").json()["files"]
    assert [t["name"] for t in trash] == ["gone.txt"]  # recoverable, not destroyed
    assert not laptop.sync().did_work


def test_a_server_delete_moves_the_local_file_to_a_local_trash(server, device) -> None:
    a, b = device("a"), device("b")
    a.write("temp.txt", "short lived")
    a.sync()
    b.sync()
    assert b.exists("temp.txt")

    a.delete("temp.txt")
    a.sync()
    report = b.sync()

    assert report.deleted_local == 1
    assert not b.exists("temp.txt")
    trashed = list((b.root / ".cloudsync" / "trash").rglob("temp.txt"))
    assert len(trashed) == 1 and trashed[0].read_bytes() == b"short lived"  # not destroyed


def test_an_edit_beats_a_delete_when_the_server_deleted_it(server, device) -> None:
    a, b = device("a"), device("b")
    a.write("doc.txt", "original")
    a.sync()
    b.sync()

    a.delete("doc.txt")
    a.sync()  # trashed on the server
    b.write("doc.txt", "edited on B before it noticed the delete")
    b.sync()

    assert server_files(server)["doc.txt"]["hash"] == sha(
        b"edited on B before it noticed the delete"
    )


def test_an_edit_beats_a_delete_when_this_side_deleted_it(server, device) -> None:
    a, b = device("a"), device("b")
    a.write("doc.txt", "original")
    a.sync()
    b.sync()

    a.write("doc.txt", "edited on A")
    a.sync()
    b.delete("doc.txt")  # B deletes without having seen A's edit
    b.sync()

    assert b.read("doc.txt") == b"edited on A"  # the edit came back
    assert server_files(server)["doc.txt"]["hash"] == sha(b"edited on A")


def test_identical_files_on_both_sides_are_adopted_without_any_transfer(server, device) -> None:
    a = device("a")
    a.write("same.txt", "identical bytes")
    a.sync()
    file_id = server_files(server)["same.txt"]["id"]

    b = device("b")
    b.write("same.txt", "identical bytes")  # already has it, never synced
    report = b.sync()

    assert report.adopted == 1 and report.uploaded == 0 and report.downloaded == 0
    versions = b.api._send("GET", f"/api/files/{file_id}/versions").json()["versions"]
    assert len(versions) == 1  # no spurious version


def test_files_still_being_written_are_left_for_later(server, device) -> None:
    laptop = device(settle_seconds=3600)
    laptop.write("download.bin", "half-written")
    # Pretend it was just touched.
    import os
    import time

    os.utime(laptop.root / "download.bin", (time.time(), time.time()))

    report = laptop.sync()

    assert report.uploaded == 0 and report.unstable == 1
    assert server_files(server) == {}


def test_internal_and_temporary_files_are_never_synced(server, device) -> None:
    laptop = device()
    laptop.write("real.txt", "real")
    laptop.write(".DS_Store", "x")
    laptop.write("draft.txt.swp", "x")
    laptop.write("~$budget.xlsx", "x")

    laptop.sync()

    assert set(server_files(server)) == {"real.txt"}


def test_unicode_and_spaces_in_names_round_trip(server, device) -> None:
    a, b = device("a"), device("b")
    a.write("Résumé 2026 — final (v2).txt", "naïve café")
    a.write("日本語/ファイル.txt", "こんにちは")
    a.sync()

    b.sync()

    assert b.read("Résumé 2026 — final (v2).txt") == "naïve café".encode()
    assert b.read("日本語/ファイル.txt") == "こんにちは".encode()
