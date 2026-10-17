"""Registration, login, JWT issuance/refresh, authorization dependency.

Implemented in Phase 2 (Authentication). See docs/architecture.md.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import rate_limit
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import invite_service, security_service, two_factor_service

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password",
)

# Clients look for exactly this text to know they should ask for a code.
TWO_FACTOR_REQUIRED = "two_factor_required"

_INVALID_REFRESH_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired refresh token",
)


def _issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register", 10, 3600))],
)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> User:
    try:
        invite = invite_service.authorize_registration(db, body.invite_code)
    except invite_service.RegistrationClosed as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    duplicate = db.execute(
        select(User).where((User.email == body.email) | (User.username == body.username))
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email or username already exists",
        )

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        storage_quota=settings.default_storage_quota_bytes,
    )
    db.add(user)
    if invite is not None:
        db.flush()
        invite_service.redeem(db, invite, user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/registration")
def registration_info(db: Session = Depends(get_db)) -> dict:
    """What the sign-up page needs: is it open, or is an invite code required."""
    return invite_service.registration_info(db)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login", 10, 60))],
)
def login(
    body: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> TokenResponse:
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()

    # Deliberately identical error for "no such user" and "wrong password" —
    # distinguishing them would tell an attacker which emails are registered.
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        if user is not None:  # a made-up email is not stored; a real account's history is
            security_service.record_login(db, user, request, success=False)
        raise _INVALID_CREDENTIALS

    if user.totp_enabled:
        # Only reached with the right password, so this does not reveal which emails exist.
        if not body.otp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=TWO_FACTOR_REQUIRED
            )
        try:
            two_factor_service.check(db, user, body.otp)
        except two_factor_service.TwoFactorFailed as exc:
            security_service.record_login(db, user, request, success=False)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    security_service.record_login(db, user, request, success=True)
    return _issue_tokens(user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("refresh", 60, 60))],
)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token, expected_type=REFRESH_TOKEN_TYPE)
        user_id = UUID(payload["sub"])
    except (TokenError, KeyError, ValueError, TypeError) as exc:
        raise _INVALID_REFRESH_TOKEN from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _INVALID_REFRESH_TOKEN

    # Rotate both tokens rather than only minting a new access token, so a
    # refresh token is single-use in practice.
    return _issue_tokens(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current_user: User = Depends(get_current_user)) -> None:
    """Log out the current user.

    Access/refresh tokens are stateless, short-lived JWTs (docs/security.md)
    and the schema (docs/architecture.md#database-design) has no session or
    token-blocklist table — adding one solely to support server-side
    revocation would be the unnecessary infrastructure Rule 2 warns against
    for a personal project. "Logging out" means the client discards its
    tokens; the access token expires on its own shortly after regardless.
    Requiring a valid token here still confirms the caller was actually
    logged in.
    """
    return None


@router.get("/security-log")
def security_log(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """Recent sign-in attempts on this account, newest first."""
    return [
        {
            "at": event.at,
            "ip": event.ip,
            "user_agent": event.user_agent,
            "success": event.success,
            "new_device": event.new_device,
        }
        for event in security_service.recent_events(db, current_user)
    ]


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
