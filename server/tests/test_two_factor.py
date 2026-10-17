"""Two-factor login (Phase 13): TOTP, recovery codes, lockout, and users without it unaffected."""

import base64

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit, totp
from app.models.user import User

# RFC 6238 appendix B: the SHA-1 test key is the ASCII string "12345678901234567890".
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_totp_matches_the_rfc_6238_test_vectors() -> None:
    # (time, expected 8-digit code); our codes are the last 6 digits of the same values.
    vectors = {
        59: "94287082",
        1111111109: "07081804",
        1111111111: "14050471",
        2000000000: "69279037",
    }
    for moment, expected in vectors.items():
        assert totp.code_at(RFC_SECRET, moment // 30, digits=8) == expected
        assert totp.code_at(RFC_SECRET, moment // 30) == expected[-6:]


def test_verify_accepts_neighbouring_windows_and_refuses_replays() -> None:
    now = 1_700_000_000.0
    step = totp.current_step(now)
    code = totp.code_at(RFC_SECRET, step)
    assert totp.verify(RFC_SECRET, code, now=now) == step
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step - 1), now=now) == step - 1
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step - 2), now=now) is None  # too old
    assert totp.verify(RFC_SECRET, code, last_step=step, now=now) is None  # already used
    assert totp.verify(RFC_SECRET, "12345", now=now) is None
    assert totp.verify(RFC_SECRET, "abcdef", now=now) is None


def _login(client, email="alice@example.com", password="password123", **extra):
    return client.post("/api/auth/login", json={"email": email, "password": password, **extra})


def _enable(client, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    setup = client.post("/api/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/Choud")
    code = totp.code_at(secret, totp.current_step())
    enabled = client.post("/api/auth/2fa/enable", json={"code": code}, headers=headers)
    assert enabled.status_code == 200, enabled.text
    return user, headers, secret, enabled.json()["recovery_codes"]


def _next_code(secret):
    """A valid code for a later step than any used so far (the replay guard needs this)."""
    return totp.code_at(secret, totp.current_step() + 1)


def test_users_without_two_factor_log_in_as_before(client: TestClient, make_user) -> None:
    make_user()
    assert _login(client).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer x"}).status_code == 401


def test_setup_needs_a_correct_code_before_it_turns_on(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    user = make_user()
    headers = auth_headers(user)
    secret = client.post("/api/auth/2fa/setup", headers=headers).json()["secret"]
    wrong = client.post("/api/auth/2fa/enable", json={"code": "000000"}, headers=headers)
    assert wrong.status_code == 422
    assert db_session.get(User, user.id).totp_enabled is False
    assert _login(client).status_code == 200  # still not required

    right = totp.code_at(secret, totp.current_step())
    assert (
        client.post("/api/auth/2fa/enable", json={"code": right}, headers=headers).status_code
        == 200
    )
    assert client.get("/api/auth/2fa", headers=headers).json() == {
        "enabled": True,
        "recovery_codes_left": 10,
    }
    assert client.post("/api/auth/2fa/setup", headers=headers).status_code == 409


def test_login_then_needs_the_code(client: TestClient, make_user, auth_headers) -> None:
    _, _, secret, _ = _enable(client, make_user, auth_headers)

    missing = _login(client)
    assert missing.status_code == 401 and missing.json()["detail"] == "two_factor_required"
    assert (
        _login(client, password="wrong-password", otp="123456").json()["detail"]
        != "two_factor_required"
    )
    assert _login(client, otp="000000").status_code == 401
    ok = _login(client, otp=_next_code(secret))
    assert ok.status_code == 200 and "access_token" in ok.json()
    # The same code cannot be used twice.
    assert _login(client, otp=_next_code(secret)).status_code == 401


def test_a_recovery_code_works_once(client: TestClient, make_user, auth_headers) -> None:
    _, headers, _, codes = _enable(client, make_user, auth_headers)
    assert len(codes) == 10 and len(set(codes)) == 10

    assert _login(client, otp=codes[0]).status_code == 200
    assert _login(client, otp=codes[0]).status_code == 401  # spent
    assert _login(client, otp=codes[1].upper()).status_code == 200  # case does not matter
    assert client.get("/api/auth/2fa", headers=headers).json()["recovery_codes_left"] == 8


def test_five_wrong_codes_lock_further_attempts(
    client: TestClient, make_user, auth_headers
) -> None:
    _, _, secret, _ = _enable(client, make_user, auth_headers)
    for _ in range(5):
        assert _login(client, otp="000000").status_code == 401
    locked = _login(client, otp=_next_code(secret))
    assert locked.status_code == 401 and "Too many" in locked.json()["detail"]


def test_turning_it_off_needs_the_password_and_a_code(
    client: TestClient, make_user, auth_headers
) -> None:
    _, headers, secret, _ = _enable(client, make_user, auth_headers)
    body = {"password": "password123", "code": _next_code(secret)}
    assert (
        client.post(
            "/api/auth/2fa/disable", json={**body, "password": "nope"}, headers=headers
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/2fa/disable", json={**body, "code": "000000"}, headers=headers
        ).status_code
        == 401
    )
    assert client.post("/api/auth/2fa/disable", json=body, headers=headers).status_code == 204
    assert _login(client).status_code == 200  # back to password only
    assert client.get("/api/auth/2fa", headers=headers).json()["enabled"] is False


def test_new_recovery_codes_replace_the_old_ones(
    client: TestClient, make_user, auth_headers
) -> None:
    _, headers, secret, old = _enable(client, make_user, auth_headers)
    fresh = client.post(
        "/api/auth/2fa/recovery-codes", json={"code": _next_code(secret)}, headers=headers
    ).json()["recovery_codes"]
    assert len(fresh) == 10 and not set(fresh) & set(old)
    assert _login(client, otp=old[0]).status_code == 401
    assert _login(client, otp=fresh[0]).status_code == 200


def test_two_factor_endpoints_need_a_login(client: TestClient) -> None:
    assert client.post("/api/auth/2fa/setup").status_code == 401
    assert client.get("/api/auth/2fa").status_code == 401


def test_me_reports_whether_two_factor_is_on(client: TestClient, make_user, auth_headers) -> None:
    _, headers, _, _ = _enable(client, make_user, auth_headers)
    assert client.get("/api/auth/me", headers=headers).json()["totp_enabled"] is True
