"""Who may register: first account free, then invite codes (or open / closed by setting)."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.invite import Invite


def _register(client, name, **extra):
    return client.post(
        "/api/auth/register",
        json={"username": name, "email": f"{name}@example.com", "password": "password123", **extra},
    )


def _mode(monkeypatch, value):
    monkeypatch.setattr(get_settings(), "registration_mode", value)


def test_first_account_needs_no_code_then_signup_needs_an_invite(client: TestClient, monkeypatch):
    _mode(monkeypatch, "invite")
    assert client.get("/api/auth/registration").json()["first_account"] is True
    assert _register(client, "owner").status_code == 201
    info = client.get("/api/auth/registration").json()
    assert info["invite_required"] is True and info["open"] is False
    assert _register(client, "stranger").status_code == 403
    assert _register(client, "stranger", invite_code="guess").status_code == 403


def test_admin_invites_work_once(client: TestClient, monkeypatch, auth_headers, db_session):
    _mode(monkeypatch, "invite")
    _register(client, "owner")
    from sqlalchemy import select

    from app.models.user import User

    owner = db_session.execute(select(User).where(User.username == "owner")).scalar_one()
    headers = auth_headers(owner)
    made = client.post(
        "/api/invites", json={"note": "for Sam", "storage_quota_bytes": 5_000_000}, headers=headers
    )
    assert made.status_code == 201
    code = made.json()["code"]
    assert len(client.get("/api/invites", headers=headers).json()) == 1

    ok = _register(client, "sam", invite_code=code)
    assert ok.status_code == 201
    sam = db_session.execute(select(User).where(User.username == "sam")).scalar_one()
    assert sam.storage_quota == 5_000_000  # the invite carried its own quota
    assert _register(client, "sam2", invite_code=code).status_code == 403  # single use
    assert client.get("/api/invites", headers=headers).json()[0]["used_at"] is not None


def test_only_the_administrator_can_make_invites(client: TestClient, make_user, auth_headers):
    admin = make_user("admin", "admin@example.com")
    other = make_user("other", "other@example.com")
    assert client.post("/api/invites", json={}, headers=auth_headers(other)).status_code == 403
    assert client.get("/api/invites", headers=auth_headers(other)).status_code == 403
    assert client.post("/api/invites", json={}, headers=auth_headers(admin)).status_code == 201
    assert client.post("/api/invites", json={}).status_code == 401


def test_expired_and_deleted_invites_do_not_work(
    client: TestClient, monkeypatch, make_user, auth_headers, db_session
):
    _mode(monkeypatch, "invite")
    admin = make_user("admin", "admin@example.com")
    headers = auth_headers(admin)
    code = client.post("/api/invites", json={}, headers=headers).json()
    row = db_session.get(Invite, code["id"])
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert _register(client, "late", invite_code=code["code"]).status_code == 403

    fresh = client.post("/api/invites", json={}, headers=headers).json()
    assert client.delete(f"/api/invites/{fresh['id']}", headers=headers).status_code == 204
    assert _register(client, "gone", invite_code=fresh["code"]).status_code == 403


def test_open_mode_lets_anyone_in_and_closed_mode_lets_nobody(
    client: TestClient, monkeypatch, make_user
):
    make_user("admin", "admin@example.com")
    _mode(monkeypatch, "open")
    assert _register(client, "anyone").status_code == 201
    _mode(monkeypatch, "closed")
    assert _register(client, "nobody").status_code == 403
    _mode(monkeypatch, "banana")  # an unknown value must fail safe, not open
    assert _register(client, "nobody2").status_code == 403
