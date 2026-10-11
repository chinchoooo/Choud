"""Phase 8: offline mode, restarts, interrupted transfers, races and conflicts.

The rule these tests defend: whatever goes wrong - network drop, crash, two
devices editing the same file - no version of anybody's data is lost.
"""

import datetime as dt
import hashlib

from cloudsync.database import QueueItem
from tests.conftest import server_files

TODAY = dt.date(2026, 10, 17)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pending(device) -> dict[tuple[str, str], QueueItem]:
    return {(i.kind, i.path): i for i in device.db.queue_items()}


# --- offline ------------------------------------------------------------------------


def test_working_offline_queues_changes_and_uploads_them_on_reconnect(server, device) -> None:
    laptop = device()
    laptop.write("existing.txt", "v1")
    laptop.sync()

    laptop.net.online = False
    laptop.write("existing.txt", "edited offline")
    laptop.write("new.txt", "created offline")
    report = laptop.sync()

    assert report.offline and report.pending == 2
    assert set(pending(laptop)) == {("upload_update", "existing.txt"), ("upload_new", "new.txt")}
    assert server_files(server)["existing.txt"]["hash"] == sha(b"v1")  # server untouched
    assert laptop.read("new.txt") == b"created offline"  # local data untouched

    laptop.net.online = True
    after = laptop.sync()

    assert after.uploaded == 2 and not after.offline and after.pending == 0
    assert server_files(server)["existing.txt"]["hash"] == sha(b"edited offline")
    assert "new.txt" in server_files(server)


def test_a_delete_made_offline_is_applied_on_reconnect(server, device) -> None:
    laptop = device()
    laptop.write("doomed.txt", "x")
    laptop.sync()

    laptop.net.online = False
    laptop.delete("doomed.txt")
    laptop.sync()
    assert pending(laptop) == {
        ("delete_remote", "doomed.txt"): pending(laptop)[("delete_remote", "doomed.txt")]
    }

    laptop.net.online = True
    laptop.sync()

    assert "doomed.txt" not in server_files(server)


def test_the_queue_survives_a_restart_of_the_client(server, device) -> None:
    laptop = device()
    laptop.write("doc.txt", "v1")
    laptop.sync()
    laptop.net.online = False
    laptop.write("doc.txt", "edited just before the app was closed")
    laptop.sync()

    relaunched = laptop.restart()  # new process, same folder

    assert ("upload_update", "doc.txt") in pending(relaunched)  # still waiting
    report = relaunched.sync()
    assert report.uploaded == 1
    assert server_files(server)["doc.txt"]["hash"] == sha(b"edited just before the app was closed")
    relaunched.db.close()


def test_a_dropped_connection_midway_loses_nothing_and_duplicates_nothing(server, device) -> None:
    laptop = device()
    for i in range(5):
        laptop.write(f"file{i}.txt", f"content {i}")
    # Allow the snapshot, then the connection dies on the third upload.
    laptop.net.before_request = lambda m, u: (
        setattr(laptop.net, "online", False)
        if laptop.net.count("POST", "/api/files/upload") >= 2
        else None
    )

    first = laptop.sync()

    assert first.offline
    uploaded_so_far = len(server_files(server))
    assert 0 < uploaded_so_far < 5

    laptop.net.online = True
    laptop.net.before_request = None
    second = laptop.sync()

    files = server_files(server)
    assert set(files) == {f"file{i}.txt" for i in range(5)}
    assert second.pending == 0
    for i in range(5):  # each exactly once: one version, no duplicates
        versions = laptop.api._send("GET", f"/api/files/{files[f'file{i}.txt']['id']}/versions")
        assert len(versions.json()["versions"]) == 1


def test_an_interrupted_large_upload_resumes_with_only_the_missing_chunks(server, device) -> None:
    laptop = device()  # chunk_threshold 10 KB, chunk_size 4 KB
    content = bytes(range(256)) * 120  # 30,720 bytes -> 8 chunks
    laptop.write("video.bin", content)
    from tests.conftest import Rule

    laptop.net.rules.append(Rule(lambda m, u: m == "POST" and u.endswith("/chunks/3"), "drop", 1))

    first = laptop.sync()

    assert first.offline
    chunks_first = laptop.net.count("POST", "/chunks/")
    assert chunks_first == 4  # chunks 0..2 sent, the 4th (index 3) dropped
    assert laptop.db.get_upload("video.bin", sha(content))  # the session id was remembered

    laptop.net.requests.clear()
    second = laptop.sync()

    assert second.uploaded == 1
    assert laptop.net.count("POST", "/chunks/") == 5  # only chunks 3..7: nothing resent
    assert server_files(server)["video.bin"]["hash"] == sha(content)
    assert laptop.db.get_upload("video.bin", sha(content)) is None  # session cleaned up


def test_a_resumed_upload_survives_a_restart_of_the_client(server, device) -> None:
    laptop = device()
    content = b"R" * 20_000
    laptop.write("big.bin", content)
    from tests.conftest import Rule

    laptop.net.rules.append(Rule(lambda m, u: m == "POST" and u.endswith("/chunks/2"), "drop", 1))
    laptop.sync()

    relaunched = laptop.restart()
    relaunched.sync()

    assert (
        relaunched.net.count("POST", "/chunks/") == 3
    )  # 2,3,4 of 5: it picked up where it stopped
    assert server_files(server)["big.bin"]["hash"] == sha(content)
    relaunched.db.close()


# --- conflicts ------------------------------------------------------------------------


def test_editing_the_same_file_on_two_devices_keeps_both_versions(server, device) -> None:
    a, b = device("a", today=lambda: TODAY), device("b", today=lambda: TODAY)
    a.write("report.txt", "original")
    a.sync()
    b.sync()

    a.write("report.txt", "A's edit")
    a.sync()
    b.write("report.txt", "B's edit")  # B never saw A's edit
    report = b.sync()

    assert report.conflicts == 1
    assert b.read("report.txt") == b"A's edit"  # the server's version holds the original path
    assert b.read("report.conflict-2026-10-17.txt") == b"B's edit"  # B's work is preserved
    # ...and the conflict copy was uploaded, so the server has both.
    files = server_files(server)
    assert files["report.txt"]["hash"] == sha(b"A's edit")
    assert files["report.conflict-2026-10-17.txt"]["hash"] == sha(b"B's edit")

    a.sync()
    assert a.read("report.conflict-2026-10-17.txt") == b"B's edit"  # A receives it too
    assert not a.sync().did_work and not b.sync().did_work


def test_a_conflict_is_detected_when_one_side_was_offline(server, device) -> None:
    a, b = device("a", today=lambda: TODAY), device("b", today=lambda: TODAY)
    a.write("plan.md", "v1")
    a.sync()
    b.sync()

    b.net.online = False
    b.write("plan.md", "B edits on a plane")
    assert b.sync().offline
    a.write("plan.md", "A edits at the office")
    a.sync()

    b.net.online = True
    report = b.sync()

    assert report.conflicts == 1
    assert b.read("plan.md") == b"A edits at the office"
    assert b.read("plan.conflict-2026-10-17.md") == b"B edits on a plane"


def test_two_files_created_independently_at_the_same_path_conflict(server, device) -> None:
    a, b = device("a", today=lambda: TODAY), device("b", today=lambda: TODAY)
    a.write("notes.txt", "from A")
    a.sync()
    b.write("notes.txt", "from B")  # same name, never synced, different content

    report = b.sync()

    assert report.conflicts == 1
    assert b.read("notes.txt") == b"from A"
    assert b.read("notes.conflict-2026-10-17.txt") == b"from B"


def test_repeated_conflicts_on_the_same_day_get_distinct_names(server, device) -> None:
    a, b = device("a", today=lambda: TODAY), device("b", today=lambda: TODAY)
    a.write("f.txt", "0")
    a.sync()
    b.sync()
    for i in (1, 2):
        a.write("f.txt", f"A{i}")
        a.sync()
        b.write("f.txt", f"B{i}")
        b.sync()

    copies = sorted(p for p in b.tree() if ".conflict-" in p)

    assert copies == ["f.conflict-2026-10-17-2.txt", "f.conflict-2026-10-17.txt"]
    assert {b.read(c) for c in copies} == {b"B1", b"B2"}  # neither overwrote the other


def test_a_write_based_on_a_stale_version_is_refused_not_applied(server, device) -> None:
    a, b = device("a", today=lambda: TODAY), device("b", today=lambda: TODAY)
    a.write("race.txt", "v1")
    a.sync()
    b.sync()
    stale = b.api.snapshot()  # B's view before A edits

    a.write("race.txt", "A's edit")
    a.sync()
    b.write("race.txt", "B's edit")
    b.api.snapshot = lambda: stale  # B acts on the stale view: the race
    report = b.sync_once()

    # The server refused B's conditional write; nothing was overwritten.
    assert report.uploaded == 0
    assert server_files(server)["race.txt"]["hash"] == sha(b"A's edit")
    assert b.read("race.txt") == b"B's edit"  # B's local work is intact

    del b.api.snapshot  # network heals: the next cycle sees the truth and makes a conflict copy
    b.sync()
    assert b.read("race.txt") == b"A's edit"
    assert b.read("race.conflict-2026-10-17.txt") == b"B's edit"


def test_a_delete_based_on_a_stale_version_does_not_trash_someone_elses_edit(
    server, device
) -> None:
    a, b = device("a"), device("b")
    a.write("keep.txt", "v1")
    a.sync()
    b.sync()
    stale = b.api.snapshot()

    a.write("keep.txt", "A's important edit")
    a.sync()
    b.delete("keep.txt")
    b.api.snapshot = lambda: stale
    b.sync_once()

    assert server_files(server)["keep.txt"]["hash"] == sha(b"A's important edit")  # not trashed

    del b.api.snapshot
    b.sync()
    assert b.read("keep.txt") == b"A's important edit"  # the edit came back to B


def test_a_file_that_changes_between_scan_and_upload_is_retried_not_corrupted(
    server, device
) -> None:
    laptop = device()
    laptop.write("moving.txt", "first")

    def edit_after_scan(method: str, url: str) -> None:
        if method == "GET" and url.endswith("/api/sync/snapshot"):
            laptop.write("moving.txt", "changed while syncing")
            laptop.net.before_request = None

    laptop.net.before_request = edit_after_scan
    first = laptop.sync_once()

    assert first.uploaded == 0 and first.errors  # refused rather than uploading mismatched bytes
    assert server_files(server) == {}

    laptop.engine._now = lambda: 10**10  # past any back-off
    laptop.sync()
    assert server_files(server)["moving.txt"]["hash"] == sha(b"changed while syncing")


# --- errors and back-off ----------------------------------------------------------------


def test_a_failing_file_backs_off_and_does_not_block_the_others(server, device) -> None:
    clock = {"now": 1000.0}
    laptop = device(now=lambda: clock["now"])
    laptop.write("bad.txt", "will fail")
    laptop.write("good.txt", "will work")
    from tests.conftest import Rule

    laptop.net.rules.append(
        Rule(lambda m, u: m == "POST" and u.endswith("/api/files/upload"), 500, 1)
    )

    first = laptop.sync_once()

    assert first.uploaded == 1 and len(first.errors) == 1  # one failed, one succeeded
    failed = next(i for i in laptop.db.queue_items())
    assert failed.attempts == 1 and failed.next_attempt > clock["now"]  # backing off

    clock["now"] += 1  # too soon
    soon = laptop.sync_once()
    assert soon.deferred == 1 and soon.uploaded == 0

    clock["now"] += 60  # past the back-off
    later = laptop.sync_once()
    assert later.uploaded == 1 and later.pending == 0
    assert set(server_files(server)) == {"bad.txt", "good.txt"}


def test_an_expired_access_token_is_refreshed_transparently(server, device) -> None:
    laptop = device()
    laptop.write("a.txt", "x")
    laptop.api._access = "not-a-valid-token"  # as if it expired

    report = laptop.sync()

    assert report.uploaded == 1 and not report.auth_required
    assert laptop.api._access != "not-a-valid-token"


def test_a_dead_login_stops_the_sync_without_touching_any_files(server, device) -> None:
    laptop = device()
    laptop.write("a.txt", "x")
    laptop.sync()
    laptop.api._access = laptop.api._refresh = "revoked"
    laptop.write("a.txt", "edited")

    report = laptop.sync()

    assert report.auth_required
    assert laptop.read("a.txt") == b"edited"
    assert "login expired" in report.summary()


def test_a_name_collision_between_a_server_file_and_folder_is_skipped(server, device) -> None:
    a = device("a")
    a.write("clash", "i am a file")
    a.write("fine.txt", "ok")
    a.sync()
    a.api.ensure_folder("clash")  # now the server also has a folder called "clash"

    b = device("b")
    report = b.sync()

    assert "clash" in report.skipped
    assert b.read("fine.txt") == b"ok"  # everything else still syncs
