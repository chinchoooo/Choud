"""Shared FastAPI dependencies, e.g. get_current_user.

Every protected endpoint from Phase 3 onward depends on `get_current_user`
(see docs/security.md#authorization) rather than trusting anything the
client supplies about who it is.
"""

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import ACCESS_TOKEN_TYPE, TokenError, decode_token
from app.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer token in the Authorization header to a User.

    Raises 401 for a missing header, a malformed/expired/wrong-type token,
    a token for a user that no longer exists, or a deactivated user.
    """
    if credentials is None:
        raise _credentials_error

    try:
        payload = decode_token(credentials.credentials, expected_type=ACCESS_TOKEN_TYPE)
    except TokenError as exc:
        raise _credentials_error from exc

    subject = payload.get("sub")
    if subject is None:
        raise _credentials_error

    try:
        user_id = UUID(subject)
    except (ValueError, TypeError) as exc:
        raise _credentials_error from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _credentials_error

    return user
