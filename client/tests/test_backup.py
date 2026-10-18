"""Milestone 3: upload-only backup of several folders, waiting for the server to be reachable."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from cloudsync.api import ApiClient
from cloudsync.backup import backup_targets, run_backup_forever
from cloudsync.config import Config, load_config
from cloudsync.database import StateDB
from cloudsync.main import EXIT_OK, main
from cloudsync.service import service_plan
from cloudsync.syncer import SyncEngine
from tests.conftest import Network, server_files

_stamp = [1_800_000_000]


def _write(root: Path, rel: str, content: bytes | str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    _stamp[0] += 10
    os.utime(path, (_stamp[0], _stamp[0]))
    return path


def _engine(server, folder: Path, state: Path, prefix: str) -> tuple[SyncEngine, Network]:
    net = Network(server.http)
    api = ApiClient(http=net, remote_prefix=prefix)
    api.login(server.email, server.password)
    state.mkdir(parents=True, exist_ok=True)
    engine = SyncEngine(
        folder,
        api,
        StateDB(state / "state.db"),
        settle_seconds=0.0,
        chunk_threshold=10_000,
        chunk_size=4_000,
        mode="backup",
        state_dir=state,
    )
    return engine, net


def test_a_backup_lands_under_its_own_server_folder(server, tmp_path) -> None:
    docs = tmp_path / "Documents"
    _write(docs, "cv.txt", "my cv")
    _write(docs, "taxes/2025.pdf", b"%PDF " + bytes(range(100)))
    engine, _ = _engine(server, docs, tmp_path / "state", "Backups/laptop/Documents")

    report = engine.sync_until_quiet()

    assert report.uploaded == 2 and not report.errors
    assert set(server_files(server)) == {
        "Backups/laptop/Documents/cv.txt",
        "Backups/laptop/Documents/taxes/2025.pdf",
    }
    assert not (docs / ".cloudsync").exists()  # nothing is written inside the user's folder
    again = engine.sync_until_quiet()
    assert not again.did_work and not again.errors  # quiet the second time


def test_a_local_delete_never_deletes_the_backup(server, tmp_path) -> None:
    docs = tmp_path / "Documents"
    keep = _write(docs, "precious.txt", "irreplaceable")
    engine, _ = _engine(server, docs, tmp_path / "state", "Backups/laptop/Documents")
    engine.sync_until_quiet()

    keep.unlink()
    report = engine.sync_until_quiet()

    assert report.deleted_remote == 0 and not report.errors
    assert "Backups/laptop/Documents/precious.txt" in server_files(server)
    assert not keep.exists()  # and it was not downloaded back either


def test_backup_never_downloads_what_is_only_on_the_server(server, tmp_path) -> None:
    docs = tmp_path / "Documents"
    docs.mkdir()
    prefix = "Backups/laptop/Documents"
    other, _ = _engine(server, tmp_path / "other", tmp_path / "other-state", prefix)
    _write(tmp_path / "other", "from-elsewhere.txt", "x")
    other.sync_until_quiet()

    engine, _ = _engine(server, docs, tmp_path / "state", prefix)
    report = engine.sync_until_quiet()

    assert report.downloaded == 0
    assert list(docs.iterdir()) == []


def test_when_both_sides_changed_this_machine_wins_as_a_new_version(server, tmp_path) -> None:
    docs = tmp_path / "Documents"
    prefix = "Backups/laptop/Documents"
    _write(docs, "notes.txt", "version one")
    engine, _ = _engine(server, docs, tmp_path / "state", prefix)
    engine.sync_until_quiet()

    # Someone else changes the backup copy on the server...
    other, _ = _engine(server, tmp_path / "x", tmp_path / "x-state", prefix)
    other.sync_until_quiet()  # (backup mode downloads nothing, so it starts empty)
    _write(tmp_path / "x", "notes.txt", "edited on the server")
    other.sync_until_quiet()
    # ...and then the laptop edits its own file.
    _write(docs, "notes.txt", "edited on the laptop")

    report = engine.sync_until_quiet()

    assert report.uploaded == 1 and report.conflicts == 0 and not report.errors
    assert (docs / "notes.txt").read_text() == "edited on the laptop"
    assert list(docs.iterdir()) == [docs / "notes.txt"]  # no conflict copies on disk
    versions = server.http.get(
        f"/api/files/{engine.api.snapshot().files['notes.txt'].id}/versions",
        headers={"Authorization": f"Bearer {engine.api._access}"},
    ).json()
    assert len(versions) >= 2  # the older content is still in history
    other.db.close()


def test_two_folders_get_distinct_server_folders_and_state(tmp_path) -> None:
    config = Config(
        backup_folders=[
            str(tmp_path / "a" / "Documents"),
            str(tmp_path / "b" / "Documents"),
            str(tmp_path / "Pictures"),
        ],
        device_name="My Laptop",
        mode="backup",
    )
    targets = backup_targets(config, tmp_path / "cfg")
    assert [t.remote_prefix for t in targets] == [
        "Backups/My Laptop/Documents",
        "Backups/My Laptop/Documents (2)",
        "Backups/My Laptop/Pictures",
    ]
    assert len({t.state_dir for t in targets}) == 3
    assert all(str(tmp_path / "cfg") in str(t.state_dir) for t in targets)


class _StopAfter(threading.Event):
    """An Event whose wait() is instant and which sets itself after N waits."""

    def __init__(self, waits: int) -> None:
        super().__init__()
        self.remaining = waits
        self.waited: list[float] = []

    def wait(self, timeout=None):
        self.waited.append(timeout)
        self.remaining -= 1
        if self.remaining <= 0:
            self.set()
        return self.is_set()


def test_the_loop_waits_while_unreachable_and_backs_up_once_it_is_back(server, tmp_path) -> None:
    docs = tmp_path / "Documents"
    _write(docs, "a.txt", "a")
    engine, _ = _engine(server, docs, tmp_path / "state", "Backups/laptop/Documents")
    answers = iter([False, False, True])
    stop = _StopAfter(waits=3)

    code = run_backup_forever(
        [("Documents", engine)],
        Config(backup_interval=900.0),
        stop,
        reachable=lambda: next(answers),
    )

    assert code == EXIT_OK
    assert stop.waited == [60.0, 60.0, 900.0]  # two short waits offline, then the long rest
    assert "Backups/laptop/Documents/a.txt" in server_files(server)


def test_the_cli_logs_in_for_backup_and_backs_up(server, tmp_path, monkeypatch, capsys) -> None:
    docs = tmp_path / "Docs"
    _write(docs, "x.txt", "x")
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLOUDSYNC_PASSWORD", server.password)
    http = Network(server.http)

    code = main(
        [
            "--config-dir", str(cfg), "login", "--server", "http://testserver",
            "--email", server.email, "--mode", "backup", "--folder", str(docs),
            "--device-name", "pc",
        ],
        http=http,
    )  # fmt: skip
    assert code == EXIT_OK
    saved = load_config(cfg)
    assert saved.mode == "backup" and saved.backup_folders == [str(docs.resolve())]

    assert main(["--config-dir", str(cfg), "sync"], http=http) == EXIT_OK
    assert "Backups/pc/Docs/x.txt" in server_files(server)
    assert main(["--config-dir", str(cfg), "status"], http=http) == EXIT_OK
    assert "Backups/pc/Docs" in capsys.readouterr().out

    missing = main(
        ["--config-dir", str(cfg), "login", "--server", "http://testserver", "--email",
         server.email, "--mode", "backup", "--folder", str(tmp_path / "nope")],
        http=http,
    )  # fmt: skip
    assert missing != EXIT_OK


def test_service_plans_start_the_client_quietly_at_login() -> None:
    home = Path("/home/me")
    linux = service_plan("linux", "/usr/bin/python3", home, Path("/cfg"))
    unit = next(iter(linux.files.values()))
    assert f"ExecStart=/usr/bin/python3 -m cloudsync.main --config-dir {Path('/cfg')} run" in unit
    assert "Nice=10" in unit and "IOSchedulingClass=idle" in unit
    assert ["systemctl", "--user", "enable", "--now", "cloudsync"] in linux.install_commands

    mac = service_plan("darwin", "/usr/bin/python3", home)
    plist = next(iter(mac.files.values()))
    assert "RunAtLoad" in plist and "LowPriorityIO" in plist

    win = service_plan("win32", r"C:\Python\python.exe", home)
    create = win.install_commands[0]
    assert create[:2] == ["schtasks", "/Create"] and "ONLOGON" in create
    assert "-m cloudsync.main run" in create[create.index("/TR") + 1]


def test_a_packaged_windows_exe_is_started_hidden_without_python() -> None:
    plan = service_plan("win32", r"C:\Tools\cloudsync.exe", Path("/home/me"), frozen=True)
    command = plan.install_commands[0][plan.install_commands[0].index("/TR") + 1]
    assert "-WindowStyle Hidden" in command
    assert r"'C:\Tools\cloudsync.exe' 'run'" in command
    assert "-m cloudsync.main" not in command


# --- upload speed limit ------------------------------------------------------------------------


def test_the_throttle_spreads_sends_out_to_the_limit() -> None:
    from cloudsync.throttle import Throttle, from_kbps

    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    throttle = Throttle(1000, clock=lambda: now[0], sleep=sleep)  # 1000 bytes per second
    assert throttle.acquire(2000) == 0  # the first send is not delayed
    assert throttle.acquire(1000) == 2.0  # it waits for the 2 s the first one "took"
    now[0] += 5.0  # a long quiet period earns no extra burst
    assert throttle.acquire(500) == 0
    assert throttle.acquire(500) == 0.5
    assert slept == [2.0, 0.5]
    assert from_kbps(0) is None and from_kbps(-3) is None
    assert from_kbps(10).rate == 10 * 1024


def test_a_limited_backup_still_uploads_everything_but_waits_between_chunks(
    server, tmp_path
) -> None:
    from cloudsync.throttle import Throttle

    docs = tmp_path / "Documents"
    _write(docs, "big.bin", bytes(range(256)) * 100)  # 25,600 bytes: chunked (threshold 10,000)
    engine, _ = _engine(server, docs, tmp_path / "state", "Backups/laptop/Documents")
    waits: list[float] = []
    clock = [0.0]
    engine.api._throttle = Throttle(
        10_000,
        clock=lambda: clock[0],
        sleep=lambda s: (waits.append(s), clock.__setitem__(0, clock[0] + s)),
    )

    report = engine.sync_until_quiet()

    assert report.uploaded == 1 and not report.errors
    assert "Backups/laptop/Documents/big.bin" in server_files(server)
    assert len(waits) >= 2 and all(w > 0 for w in waits)  # 7 chunks of 4,000 bytes, paced


def test_the_limit_command_saves_and_shows_it(tmp_path, capsys) -> None:
    cfg = tmp_path / "cfg"
    assert main(["--config-dir", str(cfg), "limit"]) == EXIT_OK
    assert "none" in capsys.readouterr().out
    assert main(["--config-dir", str(cfg), "limit", "500"]) == EXIT_OK
    assert load_config(cfg).max_upload_kbps == 500
    assert "500 KiB/s" in capsys.readouterr().out
    assert main(["--config-dir", str(cfg), "limit", "-1"]) != EXIT_OK
    assert main(["--config-dir", str(cfg), "limit", "0"]) == EXIT_OK
    assert load_config(cfg).max_upload_kbps == 0
