"""Garbage collection (Phase 15): it only ever removes storage that nothing references."""

import hashlib
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.models.upload import Upload
from app.services import gc_service
from app.services.storage_service import StorageService

DAY = 24 * 3600


def _age(path: Path, seconds: float) -> None:
    moment = time.time() - seconds
    os.utime(path, (moment, moment))


def _orphan(engine, tmp_path: Path, payload: bytes, age_seconds: float) -> str:
    """Stores bytes straight in the object store, with no database row pointing at them."""
    source = tmp_path / f"src-{uuid.uuid4().hex}"
    source.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    engine.put(digest, str(source))
    _age(engine._path_for(digest), age_seconds)
    return digest


@pytest.fixture
def root(tmp_path) -> Path:
    """The fake engine's storage root (where objects/, thumbs/, staging/, uploads/ live)."""
    return tmp_path / "engine"


def _upload(client: TestClient, headers: dict, name: str, data: bytes) -> dict:
    response = client.post(
        "/api/files/upload", files={"file": (name, data, "text/plain")}, headers=headers
    )
    assert response.status_code == 201
    return response.json()


def test_dry_run_reports_orphans_but_removes_nothing(
    db_session, fake_engine_client, root, tmp_path
):
    orphan = _orphan(fake_engine_client, tmp_path, b"nobody uses me", 10 * DAY)
    report = gc_service.run_gc(db_session, StorageService(fake_engine_client), root, delete=False)

    assert report.dry_run is True
    assert report.orphan_objects == 1
    assert report.orphan_bytes == len(b"nobody uses me")
    assert report.removed_objects == 0
    assert fake_engine_client.exists(orphan)
    assert "would remove 1 orphan" in report.summary()


def test_delete_removes_only_old_unreferenced_objects(
    client: TestClient, make_user, auth_headers, db_session, fake_engine_client, root, tmp_path
):
    headers = auth_headers(make_user())
    kept = _upload(client, headers, "kept.txt", b"i am referenced")
    trashed = _upload(client, headers, "trashed.txt", b"i am in the trash")
    client.delete(f"/api/files/{trashed['id']}", headers=headers)  # soft delete: row stays

    old_orphan = _orphan(fake_engine_client, tmp_path, b"old orphan", 10 * DAY)
    young_orphan = _orphan(fake_engine_client, tmp_path, b"young orphan", 60)

    report = gc_service.run_gc(
        db_session, StorageService(fake_engine_client), root, delete=True, grace_hours=72
    )

    assert report.removed_objects == 1
    assert not fake_engine_client.exists(old_orphan)
    assert fake_engine_client.exists(young_orphan)  # inside the grace period: could be mid-upload
    assert fake_engine_client.exists(kept["content_hash"])
    assert fake_engine_client.exists(trashed["content_hash"])  # trash is not garbage


def test_old_versions_are_not_garbage(
    client: TestClient, make_user, auth_headers, db_session, fake_engine_client, root
):
    headers = auth_headers(make_user())
    first = _upload(client, headers, "doc.txt", b"version one")
    _upload(client, headers, "doc.txt", b"version two")  # same name: a new version
    _age(fake_engine_client._path_for(first["content_hash"]), 30 * DAY)

    report = gc_service.run_gc(
        db_session, StorageService(fake_engine_client), root, delete=True, grace_hours=1
    )

    assert report.orphan_objects == 0
    assert fake_engine_client.exists(first["content_hash"])  # still restorable


def test_shared_bytes_are_kept_while_any_file_uses_them(
    client: TestClient, make_user, auth_headers, db_session, fake_engine_client, root
):
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    a = _upload(client, alice, "a.txt", b"identical bytes")
    b = _upload(client, bob, "b.txt", b"identical bytes")
    assert a["content_hash"] == b["content_hash"]
    _age(fake_engine_client._path_for(a["content_hash"]), 30 * DAY)

    client.delete(f"/api/files/{a['id']}", headers=alice)
    client.delete(f"/api/trash/{a['id']}", headers=alice)  # alice purges hers for good

    report = gc_service.run_gc(
        db_session, StorageService(fake_engine_client), root, delete=True, grace_hours=1
    )
    assert report.orphan_objects == 0
    assert fake_engine_client.exists(b["content_hash"])  # bob still needs it


def test_strays_that_are_not_objects_are_never_touched(db_session, fake_engine_client, root):
    shard = root / "objects" / "ab"
    shard.mkdir(parents=True, exist_ok=True)
    stray = shard / "notes.txt"
    stray.write_text("not an object")
    wrong_shard = shard / ("cd" + "0" * 62)  # right shape, wrong shard directory
    wrong_shard.write_text("misfiled")
    for path in (stray, wrong_shard):
        _age(path, 100 * DAY)

    report = gc_service.run_gc(db_session, StorageService(fake_engine_client), root, delete=True)

    assert stray.exists() and wrong_shard.exists()
    assert report.objects_scanned == 0


def test_an_engine_failure_is_reported_and_the_bytes_stay(
    db_session, fake_engine_client, root, tmp_path, monkeypatch
):
    orphan = _orphan(fake_engine_client, tmp_path, b"stuck", 10 * DAY)
    storage = StorageService(fake_engine_client)

    def boom(_hash):
        raise RuntimeError("engine unreachable")

    monkeypatch.setattr(storage, "remove", boom)
    report = gc_service.run_gc(db_session, storage, root, delete=True)

    assert report.removed_objects == 0
    assert report.errors and "engine unreachable" in report.errors[0]
    assert fake_engine_client.exists(orphan)


def test_orphan_thumbnails_go_but_live_ones_stay(
    client: TestClient, make_user, auth_headers, db_session, fake_engine_client, root
):
    headers = auth_headers(make_user())
    live = _upload(client, headers, "p.txt", b"live file")
    thumbs = root / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    live_thumb = thumbs / f"{live['content_hash']}-256.jpg"
    dead_thumb = thumbs / f"{'e' * 64}-256.jpg"
    other = thumbs / "readme.txt"
    for path in (live_thumb, dead_thumb, other):
        path.write_bytes(b"x")
        _age(path, 30 * DAY)

    report = gc_service.run_gc(
        db_session, StorageService(fake_engine_client), root, delete=True, grace_hours=1
    )

    assert report.removed_thumbnails == 1
    assert live_thumb.exists() and other.exists()
    assert not dead_thumb.exists()


def test_only_day_old_staging_files_are_removed(db_session, fake_engine_client, root):
    staging = root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    fresh, stale = staging / "fresh", staging / "stale"
    fresh.write_bytes(b"in flight")
    stale.write_bytes(b"crash leftover")
    _age(stale, 3 * DAY)

    gc_service.run_gc(db_session, StorageService(fake_engine_client), root, delete=True)

    assert fresh.exists()
    assert not stale.exists()


def test_abandoned_chunk_folders_are_removed_unless_a_session_owns_them(
    make_user, db_session, fake_engine_client, root
):
    user = make_user()
    uploads = root / "uploads"
    ghost, owned = str(uuid.uuid4()), str(uuid.uuid4())
    for name in (ghost, owned):
        folder = uploads / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "000000").write_bytes(b"chunk")
        _age(folder, 10 * DAY)
    db_session.add(
        Upload(
            id=uuid.UUID(owned),
            owner_id=user.id,
            file_name="f.bin",
            file_size=5,
            chunk_size=5,
            total_chunks=1,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db_session.commit()

    report = gc_service.run_gc(
        db_session, StorageService(fake_engine_client), root, delete=True, grace_hours=1
    )

    assert report.removed_upload_dirs == 1
    assert not (uploads / ghost).exists()
    assert (uploads / owned).exists()


def test_symlinks_are_ignored(db_session, fake_engine_client, root, tmp_path):
    target = tmp_path / "precious.bin"
    target.write_bytes(b"precious")
    shard = root / "objects" / "aa"
    shard.mkdir(parents=True, exist_ok=True)
    link = shard / ("aa" + "1" * 62)
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot create symlinks")
    _age(target, 100 * DAY)

    report = gc_service.run_gc(db_session, StorageService(fake_engine_client), root, delete=True)

    assert report.objects_scanned == 0
    assert target.exists()


def test_cli_reports_by_default_and_deletes_only_when_told(
    db_session, fake_engine_client, root, tmp_path, monkeypatch, capsys
):
    orphan = _orphan(fake_engine_client, tmp_path, b"cli orphan", 10 * DAY)
    monkeypatch.setattr(cli.database, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(cli, "get_storage_service", lambda: StorageService(fake_engine_client))
    monkeypatch.setattr(cli.get_settings(), "storage_root", str(root))

    assert cli.main(["gc"]) == 0
    assert "dry run" in capsys.readouterr().out
    assert fake_engine_client.exists(orphan)

    assert cli.main(["gc", "--delete", "--grace-hours", "1"]) == 0
    assert not fake_engine_client.exists(orphan)
