"""Debouncing, the run loop, and the command-line interface."""

import os
import threading
import time

from cloudsync.config import Config, load_config, save_config
from cloudsync.main import (
    EXIT_AUTH,
    EXIT_OFFLINE,
    EXIT_OK,
    EXIT_USAGE,
    build_parser,
    exit_code,
    main,
    run_forever,
)
from cloudsync.syncer import SyncReport
from cloudsync.watcher import Debouncer, FolderWatcher, _Handler


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


# --- debouncer -------------------------------------------------------------------------


def test_debouncer_fires_only_after_a_quiet_period() -> None:
    clock = FakeClock()
    debouncer = Debouncer(2.0, clock)
    assert not debouncer.ready()  # nothing happened

    debouncer.poke()
    assert debouncer.dirty and not debouncer.ready()  # too soon
    clock.now += 1.9
    assert not debouncer.ready()
    clock.now += 0.2
    assert debouncer.ready()


def test_a_burst_of_events_keeps_postponing_the_signal() -> None:
    clock = FakeClock()
    debouncer = Debouncer(2.0, clock)
    for _ in range(5):  # an editor saving: many events in quick succession
        debouncer.poke()
        clock.now += 1.0
        assert not debouncer.ready()
    clock.now += 1.5
    assert debouncer.ready()

    debouncer.reset()
    assert not debouncer.ready() and not debouncer.dirty


def test_handler_ignores_internal_and_temporary_paths(tmp_path) -> None:
    clock = FakeClock()
    debouncer = Debouncer(0, clock)
    handler = _Handler(tmp_path, debouncer)

    class Event:
        def __init__(self, src, dest=None):
            self.src_path, self.dest_path = src, dest

    for ignored in [".cloudsync/state.db", ".cloudsync/tmp/x.part", "a/.DS_Store", "n.swp"]:
        handler.on_any_event(Event(str(tmp_path / ignored)))
    assert not debouncer.dirty

    handler.on_any_event(Event(str(tmp_path / "real.txt")))
    assert debouncer.dirty

    debouncer.reset()
    handler.on_any_event(Event(str(tmp_path / "draft.swp"), str(tmp_path / "final.txt")))  # rename
    assert debouncer.dirty  # the destination counts


def test_the_real_watcher_notices_a_new_file(tmp_path) -> None:
    debouncer = Debouncer(0.0)
    watcher = FolderWatcher(tmp_path, debouncer)
    watcher.start()
    try:
        (tmp_path / "new.txt").write_text("hello")
        deadline = time.time() + 5
        while not debouncer.dirty and time.time() < deadline:
            time.sleep(0.05)
        assert debouncer.dirty
    finally:
        watcher.stop()


# --- run loop ----------------------------------------------------------------------------


class FakeDb:
    closed = False

    def close(self):
        self.closed = True


class FakeEngine:
    def __init__(self, reports):
        self.reports = list(reports)
        self.calls = 0
        self.db = FakeDb()

    def sync_until_quiet(self):
        self.calls += 1
        return self.reports.pop(0) if self.reports else SyncReport()


class FakeWatcher:
    def __init__(self, root, debouncer):
        self.debouncer = debouncer
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _config(tmp_path, **kw):
    return Config(server_url="http://x", sync_root=str(tmp_path), poll_interval=0.05, **kw)


def test_run_loop_syncs_repeatedly_and_cleans_up_on_stop(tmp_path) -> None:
    engine, stop = FakeEngine([]), threading.Event()
    watchers = []

    def factory(root, debouncer):
        watchers.append(FakeWatcher(root, debouncer))
        return watchers[-1]

    thread = threading.Thread(
        target=lambda: run_forever(engine, _config(tmp_path), stop, watcher_factory=factory)
    )
    thread.start()
    time.sleep(0.8)
    stop.set()
    thread.join(timeout=5)

    assert engine.calls >= 3  # the poll interval triggered several cycles
    assert watchers[0].started and watchers[0].stopped and engine.db.closed


def test_run_loop_syncs_promptly_when_a_local_change_settles(tmp_path) -> None:
    engine, stop = FakeEngine([]), threading.Event()
    config = _config(tmp_path, debounce_seconds=0.0)
    config.poll_interval = 60  # without a local event it would wait a minute
    holder = {}

    def factory(root, debouncer):
        holder["debouncer"] = debouncer
        return FakeWatcher(root, debouncer)

    thread = threading.Thread(
        target=lambda: run_forever(engine, config, stop, watcher_factory=factory)
    )
    thread.start()
    time.sleep(0.3)
    assert engine.calls == 1
    holder["debouncer"].poke()  # the user saved a file
    time.sleep(0.6)
    stop.set()
    thread.join(timeout=5)

    assert engine.calls >= 2


def test_run_loop_exits_when_the_login_is_dead(tmp_path) -> None:
    engine = FakeEngine([SyncReport(auth_required=True)])

    code = run_forever(engine, _config(tmp_path), threading.Event(), watcher_factory=FakeWatcher)

    assert code == EXIT_AUTH and engine.calls == 1


def test_exit_codes() -> None:
    assert exit_code(SyncReport()) == EXIT_OK
    assert exit_code(SyncReport(errors=["x"])) == 1
    assert exit_code(SyncReport(offline=True)) == EXIT_OFFLINE
    assert exit_code(SyncReport(auth_required=True)) == EXIT_AUTH


# --- CLI against the real server -------------------------------------------------------------


def test_cli_login_sync_status_logout(server, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CLOUDSYNC_PASSWORD", server.password)
    cfg_dir, folder = tmp_path / "cfg", tmp_path / "MyCloud"
    common = ["--config-dir", str(cfg_dir)]

    assert main([*common, "status"], http=server.http) == EXIT_USAGE  # not logged in yet
    assert (
        main(
            [*common, "login", "--server", "http://testserver", "--email", server.email,
             "--folder", str(folder)],
            http=server.http,
        )
        == EXIT_OK
    )  # fmt: skip
    assert load_config(cfg_dir).is_logged_in

    (folder / "docs").mkdir()
    (folder / "docs" / "a.txt").write_text("hello from the CLI")
    old = time.time() - 3600
    os.utime(folder / "docs" / "a.txt", (old, old))

    assert main([*common, "sync"], http=server.http) == EXIT_OK
    assert "1 uploaded" in capsys.readouterr().out
    files = server.new_api().snapshot().files
    assert list(files) == ["docs/a.txt"]

    assert main([*common, "status"], http=server.http) == EXIT_OK
    out = capsys.readouterr().out
    assert "Tracked files: 1" in out and "Nothing pending." in out

    assert main([*common, "logout"], http=server.http) == EXIT_OK
    assert not load_config(cfg_dir).is_logged_in
    assert main([*common, "sync"], http=server.http) == EXIT_USAGE


def test_cli_login_with_a_wrong_password_fails_cleanly(
    server, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CLOUDSYNC_PASSWORD", "wrong password")

    code = main(
        ["--config-dir", str(tmp_path / "cfg"), "login", "--server", "http://testserver",
         "--email", server.email, "--folder", str(tmp_path / "f")],
        http=server.http,
    )  # fmt: skip

    assert code == EXIT_AUTH
    assert "wrong email or password" in capsys.readouterr().err
    assert not load_config(tmp_path / "cfg").is_logged_in


def test_cli_sync_persists_refreshed_tokens(server, tmp_path, monkeypatch) -> None:
    cfg_dir = tmp_path / "cfg"
    api = server.new_api()
    save_config(
        Config(
            server_url="http://testserver", email=server.email, sync_root=str(tmp_path / "f"),
            access_token="expired", refresh_token=api._refresh,
        ),
        cfg_dir,
    )  # fmt: skip

    assert main(["--config-dir", str(cfg_dir), "sync"], http=server.http) == EXIT_OK

    assert load_config(cfg_dir).access_token != "expired"  # saved for next time


def test_unprintable_file_names_do_not_crash_the_output(capsys, monkeypatch) -> None:
    import io

    from cloudsync.main import _make_output_safe

    narrow = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr("sys.stdout", narrow)
    monkeypatch.setattr("sys.stderr", narrow)

    _make_output_safe()
    print("skipped 日本語.txt")  # would raise UnicodeEncodeError before the fix
    narrow.flush()

    assert b"skipped" in narrow.buffer.getvalue()


def test_parser_requires_a_command() -> None:
    import pytest

    with pytest.raises(SystemExit):
        build_parser().parse_args([])
