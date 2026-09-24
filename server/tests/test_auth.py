from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import security
from app.models.user import User

VALID_USER = {
    "username": "aravinth",
    "email": "aravinth@example.com",
    "password": "correct-horse-battery-staple",
}


def _register(client: TestClient, **overrides):
    payload = {**VALID_USER, **overrides}
    return client.post("/api/auth/register", json=payload)


def _register_and_login(client: TestClient) -> dict:
    _register(client)
    response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    return response.json()


# --- register -----------------------------------------------------------


def test_register_creates_user_and_returns_201(client: TestClient) -> None:
    response = _register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == VALID_USER["username"]
    assert body["email"] == VALID_USER["email"]
    assert body["is_active"] is True
    assert body["storage_quota"] > 0
    assert "id" in body and "created_at" in body


def test_register_response_never_includes_password_or_hash(client: TestClient) -> None:
    response = _register(client)

    body = response.json()
    assert "password" not in body
    assert "password_hash" not in body


def test_password_is_stored_as_an_argon2_hash_not_plaintext(
    client: TestClient, db_session: Session
) -> None:
    _register(client)

    user = db_session.query(User).filter_by(email=VALID_USER["email"]).one()
    assert user.password_hash != VALID_USER["password"]
    assert user.password_hash.startswith("$argon2")


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    _register(client)

    response = _register(client, username="someone_else")

    assert response.status_code == 409


def test_register_rejects_duplicate_username(client: TestClient) -> None:
    _register(client)

    response = _register(client, email="other@example.com")

    assert response.status_code == 409


def test_register_rejects_short_password(client: TestClient) -> None:
    response = _register(client, password="short")

    assert response.status_code == 422


def test_register_rejects_invalid_username(client: TestClient) -> None:
    response = _register(client, username="a b!")

    assert response.status_code == 422


def test_register_rejects_invalid_email(client: TestClient) -> None:
    response = _register(client, email="not-an-email")

    assert response.status_code == 422


# --- login ----------------------------------------------------------------


def test_login_succeeds_and_returns_tokens(client: TestClient) -> None:
    _register(client)

    response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["access_token"] != body["refresh_token"]


def test_login_rejects_wrong_password(client: TestClient) -> None:
    _register(client)

    response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_login_rejects_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "whatever123"},
    )

    assert response.status_code == 401


def test_login_rejects_inactive_user(client: TestClient, db_session: Session) -> None:
    _register(client)
    user = db_session.query(User).filter_by(email=VALID_USER["email"]).one()
    user.is_active = False
    db_session.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )

    assert response.status_code == 401


# --- get_current_user / GET /api/auth/me -----------------------------------


def test_me_returns_current_user_with_valid_token(client: TestClient) -> None:
    tokens = _register_and_login(client)

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == VALID_USER["email"]


def test_me_rejects_missing_token(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_me_rejects_malformed_token(client: TestClient) -> None:
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401


def test_me_rejects_expired_token(client: TestClient) -> None:
    tokens = _register_and_login(client)

    # Craft an already-expired access token for the same user by decoding
    # the valid one and re-issuing with a negative TTL.
    payload = security.decode_token(tokens["access_token"], expected_type="access")
    expired = security._create_token(  # noqa: SLF001 - deliberately using the internal helper
        payload["sub"], security.ACCESS_TOKEN_TYPE, timedelta(minutes=-5)
    )

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


def test_me_rejects_refresh_token_used_as_access_token(client: TestClient) -> None:
    tokens = _register_and_login(client)

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )

    assert response.status_code == 401


def test_me_rejects_token_for_deleted_user(client: TestClient, db_session: Session) -> None:
    tokens = _register_and_login(client)
    db_session.query(User).filter_by(email=VALID_USER["email"]).delete()
    db_session.commit()

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 401


# --- refresh ----------------------------------------------------------------


def test_refresh_issues_a_new_working_access_token(client: TestClient) -> None:
    tokens = _register_and_login(client)

    response = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["access_token"]

    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert me_response.status_code == 200


def test_refresh_rejects_an_access_token(client: TestClient) -> None:
    tokens = _register_and_login(client)

    response = client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})

    assert response.status_code == 401


def test_refresh_rejects_garbage_token(client: TestClient) -> None:
    response = client.post("/api/auth/refresh", json={"refresh_token": "not-a-real-token"})

    assert response.status_code == 401


def test_refresh_rejects_expired_refresh_token(client: TestClient) -> None:
    tokens = _register_and_login(client)
    payload = security.decode_token(tokens["refresh_token"], expected_type="refresh")
    expired = security._create_token(  # noqa: SLF001
        payload["sub"], security.REFRESH_TOKEN_TYPE, timedelta(days=-1)
    )

    response = client.post("/api/auth/refresh", json={"refresh_token": expired})

    assert response.status_code == 401


# --- logout -------------------------------------------------------------


def test_logout_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/auth/logout")

    assert response.status_code == 401


def test_logout_succeeds_with_a_valid_token(client: TestClient) -> None:
    tokens = _register_and_login(client)

    response = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 204
