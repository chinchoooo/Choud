"""Auth endpoints are rate limited per client IP."""

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _limiter_on(monkeypatch: pytest.MonkeyPatch):
    # The rest of the suite runs with the limiter off (see conftest.py).
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    rate_limit.reset()
    yield
    rate_limit.reset()


def _login(client: TestClient, ip: str | None = None, password: str = "wrong-password"):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": password},
        headers=headers,
    )


def test_login_is_blocked_after_ten_attempts_in_a_minute(client: TestClient) -> None:
    statuses = [_login(client).status_code for _ in range(12)]

    assert statuses[:10] == [401] * 10  # wrong password, but allowed to try
    assert statuses[10:] == [429, 429]


def test_blocked_response_says_when_to_retry(client: TestClient) -> None:
    for _ in range(10):
        _login(client)

    blocked = _login(client)

    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 61
    assert "too many requests" in blocked.json()["detail"].lower()


def test_each_client_ip_has_its_own_budget(client: TestClient) -> None:
    for _ in range(10):
        _login(client, ip="203.0.113.7")
    assert _login(client, ip="203.0.113.7").status_code == 429

    # A different client behind the same proxy is unaffected.
    assert _login(client, ip="198.51.100.9").status_code == 401


def test_the_first_forwarded_address_is_the_client(client: TestClient) -> None:
    # Caddy appends hops: "original-client, proxy". Only the first counts.
    for _ in range(10):
        _login(client, ip="203.0.113.7, 10.0.0.2")

    assert _login(client, ip="203.0.113.7, 10.0.0.99").status_code == 429


def test_register_has_its_own_stricter_bucket(client: TestClient) -> None:
    def register(i: int):
        return client.post(
            "/api/auth/register",
            json={
                "username": f"user{i}",
                "email": f"user{i}@example.com",
                "password": "password123",
            },
        )

    statuses = [register(i).status_code for i in range(12)]

    assert statuses[:10] == [201] * 10
    assert statuses[10:] == [429, 429]
    # Registration spam does not use up the login budget.
    assert _login(client).status_code == 401


def test_the_limiter_can_be_switched_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)

    assert all(_login(client).status_code == 401 for _ in range(15))


def test_window_expires(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock["now"])
    for _ in range(10):
        assert _login(client).status_code == 401
    assert _login(client).status_code == 429

    clock["now"] += 61  # a minute later the old attempts have aged out

    assert _login(client).status_code == 401
