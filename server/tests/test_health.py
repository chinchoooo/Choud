import pytest
from fastapi.testclient import TestClient

from app.api import health


def test_health_returns_200_when_all_components_healthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "check_database", lambda: True)
    monkeypatch.setattr(health, "check_engine", lambda: True)
    monkeypatch.setattr(health, "check_storage", lambda: True)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "database": "healthy",
        "engine": "healthy",
        "storage": "healthy",
    }


def test_health_returns_503_when_a_component_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "check_database", lambda: True)
    monkeypatch.setattr(health, "check_engine", lambda: False)
    monkeypatch.setattr(health, "check_storage", lambda: True)

    response = client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["engine"] == "unhealthy"
    assert body["database"] == "healthy"
