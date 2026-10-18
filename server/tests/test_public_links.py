"""The public-links switch: honest status, the kill switch, revoke-all and the door health check."""

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture
def public_address(monkeypatch):
    monkeypatch.setattr(get_settings(), "public_base_url", "https://files.example.net")


def _upload(client, headers, name="a.txt"):
    response = client.post(
        "/api/files/upload", files={"file": (name, b"hello", "text/plain")}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _share(client, headers, file_id):
    response = client.post("/api/shares", json={"file_id": file_id}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_instance_reports_not_configured_without_a_public_address(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    info = client.get("/api/instance", headers=headers).json()
    assert info["public_status"] == "not_configured"
    assert info["public_base_url"] is None and info["is_admin"] is True
    share = _share(client, headers, _upload(client, headers)["id"])
    assert share["public_url"] is None and share["public_status"] == "not_configured"


def test_instance_needs_a_login(client: TestClient):
    assert client.get("/api/instance").status_code == 401


def test_share_gets_a_public_url_when_configured(
    client: TestClient, make_user, auth_headers, public_address
):
    headers = auth_headers(make_user())
    share = _share(client, headers, _upload(client, headers)["id"])
    assert share["public_url"] == f"https://files.example.net/s/{share['token']}"
    assert share["public_status"] == "ready"


def test_kill_switch_pauses_public_links_only_for_the_public_door(
    client: TestClient, make_user, auth_headers, public_address
):
    headers = auth_headers(make_user())
    share = _share(client, headers, _upload(client, headers)["id"])
    page = f"/s/{share['token']}"

    paused = client.put("/api/admin/public-links", json={"enabled": False}, headers=headers)
    assert paused.status_code == 200 and paused.json()["public_status"] == "paused"

    # Through the public door: not found. Through the private door: still works.
    assert client.get(page, headers={"X-Choud-Door": "public"}).status_code == 404
    assert client.get(page).status_code == 200
    # New links say they are paused and carry no public address.
    again = _share(client, headers, _upload(client, headers, "b.txt")["id"])
    assert again["public_url"] is None and again["public_status"] == "paused"

    client.put("/api/admin/public-links", json={"enabled": True}, headers=headers)
    assert client.get(page, headers={"X-Choud-Door": "public"}).status_code == 200


def test_only_the_administrator_can_flip_the_switch(client: TestClient, make_user, auth_headers):
    make_user()  # the first account is the administrator
    other = auth_headers(make_user("bob", "bob@example.com"))
    assert (
        client.put("/api/admin/public-links", json={"enabled": False}, headers=other).status_code
        == 403
    )
    assert client.post("/api/admin/public-links/check", headers=other).status_code == 403
    assert client.get("/api/instance", headers=other).json()["is_admin"] is False


def test_health_says_which_door_and_who_you_are(client: TestClient):
    private = client.get("/s/_health").json()
    assert private["ok"] is True and private["door"] == "private"
    public = client.get(
        "/s/_health", headers={"X-Choud-Door": "public", "X-Forwarded-For": "203.0.113.9"}
    ).json()
    assert public["door"] == "public" and public["client_ip"] == "203.0.113.9"


def test_health_is_not_a_share_token(client: TestClient):
    assert client.get("/s/not-a-real-token").status_code == 404


def test_revoke_all_stops_every_link_of_mine_and_only_mine(
    client: TestClient, make_user, auth_headers
):
    mine = auth_headers(make_user())
    theirs = auth_headers(make_user("bob", "bob@example.com"))
    a = _share(client, mine, _upload(client, mine, "a.txt")["id"])
    b = _share(client, mine, _upload(client, mine, "b.txt")["id"])
    c = _share(client, theirs, _upload(client, theirs, "c.txt")["id"])

    assert client.post("/api/shares/revoke-all", headers=mine).json() == {"revoked": 2}
    assert client.get(f"/s/{a['token']}").status_code == 404
    assert client.get(f"/s/{b['token']}").status_code == 404
    assert client.get(f"/s/{c['token']}").status_code == 200
    assert client.post("/api/shares/revoke-all", headers=mine).json() == {"revoked": 0}


def test_check_reports_when_no_public_address_is_set(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    result = client.post("/api/admin/public-links/check", headers=headers).json()
    assert result["ok"] is False and "PUBLIC_BASE_URL" in result["detail"]
