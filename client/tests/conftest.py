"""Integration harness: the real server application, in process.

The sync client is tested against the actual FastAPI app (not a mock of it) so a
change on either side that breaks the contract between them fails here. The app
runs over in-memory SQLite with the server test-suite's fake storage engine, so
no Docker, PostgreSQL or running engine is needed.

`server` gives you the running app; `device(name)` gives you a simulated device:
its own sync folder, state database and login, all pointed at that one server.
"""

from __future__ import annotations

import importlib.util
import itertools
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2] / "server"

# Must be set before the server app is imported.
os.environ.setdefault("MAINTENANCE_INTERVAL_SECONDS", "0")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
sys.path.insert(0, str(SERVER_DIR))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from cloudsync.api import ApiClient  # noqa: E402
from cloudsync.database import StateDB  # noqa: E402
from cloudsync.syncer import SyncEngine  # noqa: E402


def _load_fake_engine():
    # server/tests is also a package called "tests", so load the file by path.
    spec = importlib.util.spec_from_file_location(
        "server_fake_engine", SERVER_DIR / "tests" / "fake_engine.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class Rule:
    """Make matching requests fail. `action` is "drop" (connection error) or an HTTP status."""

    match: Callable[[str, str], bool]
    action: str | int
    times: int | None = None  # None = every time


class Network:
    """A wrapper around the real HTTP client that can be switched off or made flaky.

    It records every request, can fail chosen ones (connection drop or an HTTP
    error status) and can run a hook just before a request is sent, which is how
    tests make "the server changed in between" happen at an exact moment.
    """

    def __init__(self, inner: TestClient) -> None:
        self.inner = inner
        self.online = True
        self.requests: list[tuple[str, str]] = []
        self.rules: list[Rule] = []
        self.before_request: Callable[[str, str], None] | None = None
        self.sent_headers: list[dict] = []
        self.statuses: list[int] = []

    def _gate(self, method: str, url: str, headers: dict | None = None) -> httpx.Response | None:
        self.requests.append((method, url))
        self.sent_headers.append(dict(headers or {}))
        if not self.online:
            raise httpx.ConnectError("network is down")
        if self.before_request:
            self.before_request(method, url)
        for rule in list(self.rules):
            if rule.match(method, url):
                if rule.times is not None:
                    rule.times -= 1
                    if rule.times <= 0:
                        self.rules.remove(rule)
                if rule.action == "drop":
                    raise httpx.ConnectError("connection dropped")
                return httpx.Response(
                    int(rule.action),
                    json={"detail": "injected failure"},
                    request=httpx.Request(method, url),
                )
        return None

    def request(self, method: str, url: str, **kwargs):
        injected = self._gate(method, url, kwargs.get("headers"))
        response = injected if injected is not None else self.inner.request(method, url, **kwargs)
        self.statuses.append(response.status_code)
        return response

    def stream(self, method: str, url: str, **kwargs):
        injected = self._gate(method, url, kwargs.get("headers"))
        if injected is not None:
            from contextlib import contextmanager

            @contextmanager
            def failed():
                yield injected

            return failed()
        return self.inner.stream(method, url, **kwargs)

    def count(self, method: str, fragment: str) -> int:
        return sum(1 for m, u in self.requests if m == method and fragment in u)

    def close(self) -> None:  # the shared inner client is closed by the server fixture
        pass


@dataclass
class Server:
    http: TestClient
    engine: object  # FakeEngineClient
    email: str
    password: str

    def new_api(self, http=None) -> ApiClient:
        api = ApiClient(http=http or self.http)
        api.login(self.email, self.password)
        return api


@pytest.fixture
def server(tmp_path, monkeypatch):
    from app.core.database import Base, get_db
    from app.main import app
    from app.models import file, file_version, folder, upload  # noqa: F401
    from app.services import file_service, trash_service, upload_service
    from app.services.storage_service import StorageService

    fake = _load_fake_engine().FakeEngineClient(tmp_path / "engine")
    db_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=db_engine)
    make_session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def override_get_db():
        session = make_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(file_service.settings, "storage_root", str(tmp_path / "server-storage"))
    for module in (file_service, upload_service, trash_service):
        monkeypatch.setattr(module, "get_storage_service", lambda: StorageService(fake))

    http = TestClient(app)
    http.post(
        "/api/auth/register",
        json={"username": "tester", "email": "tester@example.com", "password": "correct horse"},
    ).raise_for_status()
    try:
        yield Server(http, fake, "tester@example.com", "correct horse")
    finally:
        app.dependency_overrides.clear()
        http.close()
        db_engine.dispose()


_clock = itertools.count(1_700_000_000)


class Device:
    """One simulated computer: a sync folder + state database + its own login."""

    def __init__(self, server: Server, root: Path, **engine_options) -> None:
        self.server = server
        self.root = root
        self.net = Network(server.http)
        self.api = server.new_api(self.net)
        self.db = StateDB(root / ".cloudsync" / "state.db")
        options = {"settle_seconds": 0.0, "chunk_threshold": 10_000, "chunk_size": 4_000}
        options.update(engine_options)
        self.engine = SyncEngine(root, self.api, self.db, **options)

    # --- local filesystem helpers -------------------------------------------------

    def write(self, rel: str, content: bytes | str) -> Path:
        data = content.encode() if isinstance(content, str) else content
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # A distinct, increasing mtime: two quick edits must never look unchanged.
        stamp = next(_clock)
        os.utime(path, (stamp, stamp))
        return path

    def read(self, rel: str) -> bytes:
        return (self.root / rel).read_bytes()

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()

    def delete(self, rel: str) -> None:
        (self.root / rel).unlink()

    def tree(self) -> set[str]:
        """Synced files on disk, relative and '/'-separated (internal dir excluded)."""
        found = set()
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d != ".cloudsync"]
            for name in filenames:
                found.add((Path(dirpath) / name).relative_to(self.root).as_posix())
        return found

    # --- syncing ---------------------------------------------------------------------

    def sync(self):
        return self.engine.sync_until_quiet()

    def sync_once(self):
        return self.engine.sync_once()

    def restart(self, **engine_options) -> Device:
        """Simulate quitting and relaunching the client: new objects, same folder."""
        self.db.close()
        return Device(self.server, self.root, **engine_options)


@pytest.fixture
def device(server, tmp_path):
    created: list[Device] = []

    def make(name: str = "laptop", **engine_options) -> Device:
        dev = Device(server, tmp_path / f"sync-{name}", **engine_options)
        created.append(dev)
        return dev

    yield make
    for dev in created:
        dev.db.close()


def server_files(server: Server, device_api: ApiClient | None = None) -> dict[str, dict]:
    """Path -> snapshot entry for the account, straight from the API."""
    api = device_api or server.new_api()
    return {
        path: {"hash": f.content_hash, "size": f.size, "id": f.id, "version": f.version_id}
        for path, f in api.snapshot().files.items()
    }
