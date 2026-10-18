"""Request guards, headers, CORS, the derived share key and the per-route rate limits."""

import hashlib
import hmac
import uuid
from types import SimpleNamespace

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import share_service


def test_security_headers_are_set(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"


def test_auth_responses_are_never_cached(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"email": "x@example.com", "password": "nope-nope"})
    assert res.headers["cache-control"] == "no-store"


def test_oversized_bodies_are_refused_before_being_read(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "max_request_bytes", 100)
    res = client.post(
        "/api/auth/login", content=b"x" * 500, headers={"content-type": "application/json"}
    )
    assert res.status_code == 413


def test_cross_origin_requests_get_no_cors_headers_by_default(client: TestClient) -> None:
    res = client.options(
        "/api/files",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in res.headers


def test_share_unlock_cookie_is_not_signed_with_the_raw_secret() -> None:
    share = SimpleNamespace(id=uuid.uuid4(), password_hash="hash")
    expires = 4_000_000_000
    fingerprint = hashlib.sha256(b"hash").hexdigest()[:16]
    message = f"{share.id}:{expires}:{fingerprint}".encode()
    forged = hmac.new(get_settings().jwt_secret.encode(), message, hashlib.sha256).hexdigest()
    assert not share_service.is_unlocked(share, f"{expires}.{forged}", now=1.0)
    assert share_service.is_unlocked(
        share, share_service.make_unlock_value(share, now=1.0), now=2.0
    )


def test_expensive_routes_carry_a_rate_limit() -> None:
    wanted = {
        ("POST", "/api/files/upload"),
        ("GET", "/api/files/{file_id}/download"),
        ("POST", "/api/uploads"),
        ("POST", "/api/uploads/{upload_id}/chunks/{index}"),
        ("POST", "/api/uploads/{upload_id}/complete"),
        ("POST", "/api/media/token"),
        ("POST", "/api/media/thumbs"),
        ("GET", "/api/search"),
    }
    limited = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        names = {getattr(d.call, "__qualname__", "") for d in route.dependant.dependencies}
        if any("rate_limit" in n for n in names):
            limited |= {(m, route.path) for m in route.methods}
    assert wanted <= limited, wanted - limited
