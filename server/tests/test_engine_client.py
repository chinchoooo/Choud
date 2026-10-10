"""EngineClient: whole-file calls get a long timeout, control calls a short one."""

import httpx
import pytest

from app.services.engine_client import EngineClient


class _Recorder:
    def __init__(self) -> None:
        self.timeouts: dict[str, float] = {}

    def post(self, url: str, json: dict, timeout: float) -> httpx.Response:
        self.timeouts[url] = timeout
        body = {
            "/hash": {"hash": "h"},
            "/objects/exists": {"exists": True},
            "/objects/put": {"size": 1},
            "/objects/get": {"size": 1},
            "/objects/delete": {"deleted": True},
            "/chunks/write": {},
            "/chunks/finalize": {"hash": "h", "size": 1},
            "/chunks/abandon": {"removed": True},
        }
        path = "/" + url.split("//", 1)[1].split("/", 1)[1]
        return httpx.Response(200, json=body[path], request=httpx.Request("POST", url))


@pytest.fixture
def timeouts(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    recorder = _Recorder()
    monkeypatch.setattr(httpx, "post", recorder.post)
    return recorder.timeouts


def _by_path(timeouts: dict[str, float]) -> dict[str, float]:
    return {"/" + url.split("//", 1)[1].split("/", 1)[1]: t for url, t in timeouts.items()}


def test_whole_file_calls_use_the_long_timeout(timeouts: dict[str, float]) -> None:
    client = EngineClient(base_url="http://engine:9000")
    client._timeout, client._data_timeout = 5.0, 1800.0

    client.hash_file("/p")
    client.put("h", "/p")
    client.get("h", "/p")
    client.write_chunk("u", 0, "/p")
    client.finalize_chunks("u", 1)

    assert set(_by_path(timeouts).values()) == {1800.0}


def test_control_calls_keep_the_short_timeout(timeouts: dict[str, float]) -> None:
    client = EngineClient(base_url="http://engine:9000")
    client._timeout, client._data_timeout = 5.0, 1800.0

    client.exists("h")
    client.delete("h")
    client.abandon_chunks("u")

    assert set(_by_path(timeouts).values()) == {5.0}


def test_data_timeout_is_far_longer_than_the_control_timeout_by_default() -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    assert settings.engine_data_timeout_seconds >= 600
    assert settings.engine_timeout_seconds <= 30
