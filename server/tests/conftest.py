import os

# Set before the app is imported: no background housekeeping loop and no auth
# rate limiting during tests (test_rate_limit.py / test_maintenance.py turn them
# on explicitly when they are what is under test).
os.environ.setdefault("MAINTENANCE_INTERVAL_SECONDS", "0")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("REGISTRATION_MODE", "open")
os.environ.setdefault("INDEX_INTERVAL_SECONDS", "0")
os.environ.setdefault("THUMB_INTERVAL_SECONDS", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app

# Import every model so its table registers on Base.metadata before
# create_all runs below. Add new models here as later phases land.
from app.models import (  # noqa: F401
    activity,
    favorite,
    file,
    file_text,
    file_version,
    folder,
    invite,
    login_event,
    recovery_code,
    share,
    upload,
)
from app.models.user import User


@pytest.fixture
def db_session() -> Session:
    """A fresh, isolated database for every test.

    By default an in-memory SQLite database — production always runs
    PostgreSQL (see docker-compose.yml), but a real server isn't needed to
    exercise the ORM/API layer (see app/core/types.py's GUID type, which is
    what makes this possible).

    SQLite does not enforce foreign keys, so a bug that only Postgres would
    reject can pass here (that is how the 'delete a folder that still has
    trashed files' bug stayed hidden). To run the suite against a real
    PostgreSQL instead, point TEST_DATABASE_URL at a *disposable* database:

        TEST_DATABASE_URL=postgresql+psycopg2://cloud:pw@127.0.0.1:55432/personal_cloud pytest

    Every table is created before and dropped after each test, so never aim
    this at a database that holds data you care about.
    """
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if test_database_url:
        engine = create_engine(test_database_url)
        # Start from a clean slate even if an earlier run was killed mid-test.
        Base.metadata.drop_all(bind=engine)
    else:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def fake_engine_client(tmp_path):
    """A `FakeEngineClient` rooted in this test's temp dir.

    Exposed as its own fixture (rather than only living inside
    `_isolated_storage_root` below) so tests can inspect what actually got
    written to "disk" — e.g. to confirm a duplicate upload didn't store
    the bytes twice (docs/storage.md#deduplication).
    """
    from tests.fake_engine import FakeEngineClient

    return FakeEngineClient(tmp_path / "engine")


@pytest.fixture(autouse=True)
def _isolated_storage_root(tmp_path, fake_engine_client, monkeypatch: pytest.MonkeyPatch):
    """Point file uploads at a throwaway temp dir instead of `/data/cloud`,
    and swap the real engine HTTP client for `FakeEngineClient` so the
    test suite doesn't need a running C++ engine process.

    `app.services.file_service` reads `settings.storage_root` once at
    import time and reuses that `Settings` object, so we mutate the
    attribute in place rather than relying on env vars taking effect late.
    """
    from app.services import file_service as file_service_module
    from app.services import thumbnail_service as thumbnail_service_module
    from app.services import trash_service as trash_service_module
    from app.services import upload_service as upload_service_module
    from app.services.storage_service import StorageService

    monkeypatch.setattr(file_service_module.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(
        file_service_module,
        "get_storage_service",
        lambda: StorageService(fake_engine_client),
    )
    # upload_service imports get_storage_service into its own module
    # namespace (`from ... import get_storage_service`), so it needs its
    # own patch target — patching file_service_module's doesn't affect it.
    monkeypatch.setattr(
        upload_service_module,
        "get_storage_service",
        lambda: StorageService(fake_engine_client),
    )
    monkeypatch.setattr(
        trash_service_module,
        "get_storage_service",
        lambda: StorageService(fake_engine_client),
    )
    monkeypatch.setattr(
        thumbnail_service_module,
        "get_storage_service",
        lambda: StorageService(fake_engine_client),
    )


@pytest.fixture
def make_user(db_session: Session):
    """Create a persisted user directly in the test DB (no HTTP round trip)."""
    from app.core.config import get_settings
    from app.core.security import hash_password

    settings = get_settings()

    def _make(
        username: str = "alice", email: str = "alice@example.com", password: str = "password123"
    ) -> User:
        new_user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            storage_quota=settings.default_storage_quota_bytes,
        )
        db_session.add(new_user)
        db_session.commit()
        db_session.refresh(new_user)
        return new_user

    return _make


@pytest.fixture
def auth_headers():
    def _headers(user: User) -> dict:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return _headers
