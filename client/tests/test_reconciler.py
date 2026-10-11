"""The three-way decision table, row by row, and plan-level behaviour."""

import pytest

from cloudsync.api import RemoteFile, RemoteSnapshot
from cloudsync.database import Entry
from cloudsync.reconciler import Kind, decide, plan
from cloudsync.scanner import LocalFile, ScanResult


def L(h: str, path="f.txt") -> LocalFile:
    return LocalFile(path, 1, 1, h)


def R(h: str, version="v1", file_id="f1", path="f.txt") -> RemoteFile:
    return RemoteFile(file_id, path, 1, h, version)


def B(h: str, version="v1", file_id="f1", path="f.txt") -> Entry:
    return Entry(path, file_id, h, version, 1, 1)


# (local, remote, base, expected) - every row of the table in reconciler.py
TABLE = [
    pytest.param(None, None, None, None, id="nothing anywhere"),
    pytest.param(None, None, B("a"), Kind.FORGET, id="gone on both sides"),
    pytest.param(L("a"), None, None, Kind.UPLOAD_NEW, id="new locally"),
    pytest.param(None, R("a"), None, Kind.DOWNLOAD, id="new on the server"),
    pytest.param(L("a"), None, B("a"), Kind.DELETE_LOCAL, id="server deleted, local unchanged"),
    pytest.param(
        L("b"), None, B("a"), Kind.UPLOAD_NEW, id="server deleted, local edited -> edit wins"
    ),
    pytest.param(
        None, R("a", "v1"), B("a", "v1"), Kind.DELETE_REMOTE, id="local deleted, server unchanged"
    ),
    pytest.param(
        None,
        R("b", "v2"),
        B("a", "v1"),
        Kind.DOWNLOAD,
        id="local deleted, server edited -> edit wins",
    ),
    pytest.param(L("a"), R("a"), None, Kind.ADOPT, id="same bytes, no base"),
    pytest.param(L("a"), R("b"), None, Kind.CONFLICT, id="different bytes, no base"),
    pytest.param(L("a"), R("a", "v1"), B("a", "v1"), None, id="in sync"),
    pytest.param(
        L("b"), R("b", "v2"), B("a", "v1"), Kind.ADOPT, id="both changed to the same bytes"
    ),
    pytest.param(L("b"), R("a", "v1"), B("a", "v1"), Kind.UPLOAD_UPDATE, id="only local changed"),
    pytest.param(L("a"), R("b", "v2"), B("a", "v1"), Kind.DOWNLOAD, id="only server changed"),
    pytest.param(L("b"), R("c", "v2"), B("a", "v1"), Kind.CONFLICT, id="both changed differently"),
    pytest.param(
        L("a"), R("a", "v2"), B("a", "v1"), Kind.ADOPT, id="server version moved but bytes equal"
    ),
    pytest.param(
        L("a"), R("z", "v1"), B("a", "v1"), Kind.CONFLICT, id="inconsistent base -> keep both"
    ),
    pytest.param(
        L("b"),
        R("b2", "v1", file_id="other"),
        B("a", "v1"),
        Kind.CONFLICT,
        id="server file replaced",
    ),
]


@pytest.mark.parametrize("local, remote, base, expected", TABLE)
def test_decision_table(local, remote, base, expected) -> None:
    assert decide(local, remote, base) == expected


def test_an_edit_always_beats_a_delete_in_both_directions() -> None:
    # Whoever deleted can redo it; the edit cannot be recreated (Rule 5).
    assert decide(L("edited"), None, B("original")) == Kind.UPLOAD_NEW
    assert decide(None, R("edited", "v2"), B("original", "v1")) == Kind.DOWNLOAD


# --- plan --------------------------------------------------------------------


def scan_of(*files: LocalFile, dirs=(), unstable=()) -> ScanResult:
    return ScanResult(files={f.path: f for f in files}, dirs=set(dirs), unstable=set(unstable))


def remote_of(*files: RemoteFile, folders=()) -> RemoteSnapshot:
    return RemoteSnapshot(folders={p: f"id-{p}" for p in folders}, files={f.path: f for f in files})


def kinds(p) -> list[tuple[str, str]]:
    return [(a.kind.value, a.path) for a in p.actions]


def test_plan_orders_downloads_before_uploads_before_deletes() -> None:
    p = plan(
        scan_of(L("n", "new-local.txt"), L("a", "stale.txt")),
        remote_of(
            R("d", path="new-remote.txt", file_id="r1"), R("x", "v2", "r2", "gone-local.txt")
        ),
        {
            "stale.txt": B("a", path="stale.txt", file_id="s1"),
            "gone-local.txt": B("x", "v2", "r2", "gone-local.txt"),
        },
    )

    assert kinds(p) == [
        ("download", "new-remote.txt"),
        ("upload_new", "new-local.txt"),
        ("delete_local", "stale.txt"),
        ("delete_remote", "gone-local.txt"),
    ]


def test_unstable_files_are_left_completely_alone() -> None:
    # Still being written: neither upload it nor mistake it for a delete.
    p = plan(
        scan_of(unstable=["busy.bin"]),
        remote_of(R("a", path="busy.bin")),
        {"busy.bin": B("a", path="busy.bin")},
    )

    assert p.actions == []


def test_a_server_folder_missing_locally_is_created_parents_first() -> None:
    p = plan(scan_of(), remote_of(folders=["a/b/c", "a", "a/b", "z"]), {})

    assert p.mkdir_local == ["a", "z", "a/b", "a/b/c"]
    assert p.mkdir_remote == []


def test_a_local_folder_missing_on_the_server_is_created_there() -> None:
    p = plan(scan_of(dirs=["empty", "x/y", "x"]), remote_of(folders=["x"]), {})

    assert p.mkdir_remote == ["empty", "x/y"]
    assert p.mkdir_local == []


def test_file_vs_folder_collisions_are_skipped_not_synced() -> None:
    p = plan(
        scan_of(L("a", "clash"), L("b", "clash/inside.txt"), L("c", "fine.txt")),
        remote_of(folders=["clash"]),
        {},
    )

    assert kinds(p) == [("upload_new", "fine.txt")]
    assert "clash" in p.skipped
    assert "clash/inside.txt" in p.skipped  # inside a blocked path
    assert p.mkdir_local == []  # and the folder is not created over the file


def test_server_file_and_server_folder_with_the_same_path_are_skipped() -> None:
    p = plan(scan_of(), remote_of(R("a", path="dup"), folders=["dup"]), {})

    assert p.actions == [] and "dup" in p.skipped


def test_a_server_file_this_machine_cannot_hold_is_skipped_and_not_deleted(monkeypatch) -> None:
    monkeypatch.setattr(
        "cloudsync.reconciler.path_problem", lambda path: "bad" if "bad" in path else None
    )
    p = plan(
        scan_of(),
        remote_of(R("a", path="bad:name.txt", file_id="b1")),
        {"bad:name.txt": B("a", path="bad:name.txt", file_id="b1")},
    )

    # Without this guard the missing local file would look like "deleted here"
    # and the server copy would be trashed.
    assert p.actions == []
    assert p.skipped == {"bad:name.txt": "bad"}


def test_in_sync_tree_plans_nothing() -> None:
    p = plan(
        scan_of(L("a", "docs/a.txt"), dirs=["docs"]),
        remote_of(R("a", path="docs/a.txt"), folders=["docs"]),
        {"docs/a.txt": B("a", path="docs/a.txt")},
    )

    assert p.actions == [] and p.mkdir_local == [] and p.mkdir_remote == []
