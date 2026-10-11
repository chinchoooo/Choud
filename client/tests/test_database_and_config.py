import json
import os
import sys

import pytest

from cloudsync.config import Config, load_config, save_config
from cloudsync.database import Entry, StateDB


def _entry(path="a.txt", **overrides) -> Entry:
    base = dict(path=path, file_id="f1", content_hash="h1", version_id="v1", size=3, mtime_ns=111)
    base.update(overrides)
    return Entry(**base)


@pytest.fixture
def db(tmp_path):
    database = StateDB(tmp_path / ".cloudsync" / "state.db")
    yield database
    database.close()


def test_entries_round_trip_and_update(db: StateDB) -> None:
    assert db.get_entry("a.txt") is None

    db.put_entry(_entry())
    db.put_entry(_entry(content_hash="h2", version_id="v2"))  # upsert

    assert db.get_entry("a.txt") == _entry(content_hash="h2", version_id="v2")
    assert list(db.all_entries()) == ["a.txt"]

    db.delete_entry("a.txt")
    assert db.get_entry("a.txt") is None


def test_update_stat_only_changes_size_and_mtime(db: StateDB) -> None:
    db.put_entry(_entry())

    db.update_stat("a.txt", size=99, mtime_ns=222)

    assert db.get_entry("a.txt") == _entry(size=99, mtime_ns=222)


def test_state_survives_reopening_the_database(tmp_path) -> None:
    path = tmp_path / "state.db"
    first = StateDB(path)
    first.put_entry(_entry())
    first.replace_queue([("upload", "a.txt")], now=1.0)
    first.put_upload("big.bin", "hash", "upload-1")
    first.set_meta("k", "v")
    first.close()

    second = StateDB(path)

    assert second.get_entry("a.txt") is not None
    assert [(i.kind, i.path) for i in second.queue_items()] == [("upload", "a.txt")]
    assert second.get_upload("big.bin", "hash") == "upload-1"
    assert second.get_meta("k") == "v"
    second.close()


def test_replace_queue_adds_removes_and_keeps_backoff(db: StateDB) -> None:
    db.replace_queue([("upload", "a"), ("download", "b")], now=1.0)
    db.queue_failed("upload", "a", "boom", next_attempt=500.0)

    db.replace_queue([("upload", "a"), ("delete_local", "c")], now=2.0)

    items = {(i.kind, i.path): i for i in db.queue_items()}
    assert set(items) == {("upload", "a"), ("delete_local", "c")}  # b dropped, c added
    assert items[("upload", "a")].attempts == 1  # backoff state preserved
    assert items[("upload", "a")].last_error == "boom"
    assert items[("upload", "a")].next_attempt == 500.0
    assert items[("delete_local", "c")].attempts == 0


def test_queue_done_and_failed(db: StateDB) -> None:
    db.replace_queue([("upload", "a")], now=1.0)
    db.queue_failed("upload", "a", "x" * 1000, next_attempt=9.0)
    assert db.queue_get("upload", "a").attempts == 1
    assert len(db.queue_get("upload", "a").last_error) == 500  # truncated

    db.queue_done("upload", "a")

    assert db.queue_items() == []


def test_upload_sessions_are_keyed_by_path_and_content(db: StateDB) -> None:
    db.put_upload("v.mp4", "hash-1", "session-1")
    db.put_upload("v.mp4", "hash-2", "session-2")  # file changed again: a new session

    assert db.get_upload("v.mp4", "hash-1") == "session-1"
    assert db.get_upload("v.mp4", "hash-2") == "session-2"
    db.delete_upload("v.mp4", "hash-1")
    assert db.get_upload("v.mp4", "hash-1") is None
    assert db.get_upload("v.mp4", "hash-2") == "session-2"


# --- config -------------------------------------------------------------------


def test_missing_config_loads_as_logged_out_defaults(tmp_path) -> None:
    config = load_config(tmp_path)

    assert not config.is_logged_in
    assert config.poll_interval > 0


def test_config_round_trip_and_unknown_keys_are_ignored(tmp_path) -> None:
    saved = Config(
        server_url="http://x",
        email="a@b.c",
        sync_root=str(tmp_path / "sync"),
        refresh_token="r",
        access_token="a",
    )
    path = save_config(saved, tmp_path)
    data = json.loads(path.read_text())
    data["field_from_a_newer_version"] = 1
    path.write_text(json.dumps(data))

    loaded = load_config(tmp_path)

    assert loaded.server_url == "http://x" and loaded.is_logged_in
    assert loaded.root == tmp_path / "sync"
    assert loaded.state_dir == tmp_path / "sync" / ".cloudsync"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_config_file_is_private_to_the_user(tmp_path) -> None:
    path = save_config(Config(server_url="http://x", refresh_token="secret"), tmp_path)

    assert (os.stat(path).st_mode & 0o777) == 0o600
