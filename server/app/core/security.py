"""Password hashing and JWT issuance/verification.

See docs/security.md#passwords-and-tokens: Argon2id for passwords,
short-lived JWTs signed with a secret that lives only in the environment.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

from app.core.config import get_settings

settings = get_settings()
_hasher = PasswordHasher()

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id. Never store the raw password."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored Argon2id hash.

    Returns False (never raises) on any mismatch or malformed hash, so
    callers can't accidentally leak which failure mode occurred.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False


class TokenError(Exception):
    """Raised for any invalid, expired, malformed, or wrong-type token."""


def _create_token(user_id: UUID, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID) -> str:
    return _create_token(
        user_id,
        ACCESS_TOKEN_TYPE,
        timedelta(minutes=settings.access_token_expire_minutes),
    )


MEDIA_TOKEN_TYPE = "media"
MEDIA_TOKEN_MINUTES = 60


def create_media_token(user_id: UUID) -> str:
    """A short-lived, read-only token that goes in a URL path, for `<img>`/`<video>` tags.

    Browsers and media players can't attach an Authorization header to those, so
    the content/thumbnail routes under /api/media/ accept this instead. It is a
    different token type from the access token: it cannot call any other API, and
    it expires after an hour.
    """
    return _create_token(user_id, MEDIA_TOKEN_TYPE, timedelta(minutes=MEDIA_TOKEN_MINUTES))


def create_refresh_token(user_id: UUID) -> str:
    return _create_token(
        user_id,
        REFRESH_TOKEN_TYPE,
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str, expected_type: str) -> dict:
    """Decode and validate a JWT, raising TokenError on any problem.

    Checks signature, expiry (handled by PyJWT itself) and that the token's
    `type` claim matches what the caller expects — an access token can't be
    used where a refresh token is required, and vice versa.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token")

    return payload
