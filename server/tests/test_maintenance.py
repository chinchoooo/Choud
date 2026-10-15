"""Housekeeping: expired upload sessions are swept without any manual step."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core import maintenance
from app.models.upload import Upload


def _session_factory(db_session: Session):
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)


def _make_upload(db: Session, owner_id, *, expired: bool, status: str = "pending") -> Upload:
    delta = timedelta(hours=-1) if expired else timedelta(hours=1)
    upload = Upload(
        owner_id=owner_id,
        file_name="x.bin",
        file_size=10,
        chunk_size=10,
        total_chunks=1,
        status=status,
        expires_at=datetime.now(UTC) + delta,
    )
    db.add(upload)
    db.commit()
    return upload


def test_run_once_removes_expired_pending_sessions_only(db_session: Session, make_user) -> None:
    user = make_user()
    expired = _make_upload(db_session, user.id, expired=True)
    live = _make_upload(db_session, user.id, expired=False)
    expired_id, live_id = expired.id, live.id

    result = maintenance.run_maintenance_once(_session_factory(db_session))

    assert result == {"uploads_swept": 1, "preview_cache_evicted": 0}
    db_session.expire_all()
    assert db_session.get(Upload, expired_id) is None
    assert db_session.get(Upload, live_id) is not None


def test_run_once_with_nothing_to_do_is_a_quiet_no_op(db_session: Session) -> None:
    assert maintenance.run_maintenance_once(_session_factory(db_session)) == {
        "uploads_swept": 0,
        "preview_cache_evicted": 0,
    }


def test_run_once_swallows_and_logs_failures(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(_db):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(maintenance.upload_service, "sweep_expired_uploads", boom)

    with caplog.at_level(logging.ERROR):
        result = maintenance.run_maintenance_once(_session_factory(db_session))

    assert result == {}  # housekeeping must never take the API down
    assert "maintenance run failed" in caplog.text


def test_loop_runs_repeatedly_and_survives_a_failing_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def flaky() -> dict:
        calls.append(1)
        if len(calls) == 1:
            return {}  # a failed run (already logged inside run_maintenance_once)
        return {"uploads_swept": 0}

    monkeypatch.setattr(maintenance, "run_maintenance_once", flaky)

    async def scenario() -> None:
        task = asyncio.create_task(maintenance.maintenance_loop(0.01))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert len(calls) >= 3


def test_app_starts_and_stops_the_loop_with_its_lifespan(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    from app.core.config import get_settings
    from app.main import app, lifespan

    started = []

    async def fake_loop(interval: float) -> None:
        started.append(interval)
        await asyncio.sleep(3600)

    monkeypatch.setattr("app.main.maintenance_loop", fake_loop)
    monkeypatch.setattr(get_settings(), "maintenance_interval_seconds", 5)

    async def run() -> None:
        async with lifespan(app):
            await asyncio.sleep(0.01)

    asyncio.run(run())

    assert started == [5]


def test_interval_zero_disables_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.main import app, lifespan

    started = []
    monkeypatch.setattr("app.main.maintenance_loop", lambda interval: started.append(interval))
    monkeypatch.setattr(get_settings(), "maintenance_interval_seconds", 0)

    async def run() -> None:
        async with lifespan(app):
            pass

    asyncio.run(run())

    assert started == []
