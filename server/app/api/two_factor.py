"""/api/auth/2fa: turn authenticator-app login on and off (Phase 13)."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import rate_limit
from app.core.security import verify_password
from app.models.user import User
from app.services import two_factor_service
from app.services.errors import ConflictError, ValidationError

router = APIRouter(prefix="/api/auth/2fa", tags=["two-factor"])


class CodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class DisableBody(CodeBody):
    password: str = Field(min_length=1, max_length=256)


class SetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class RecoveryCodes(BaseModel):
    recovery_codes: list[str]


class TwoFactorStatus(BaseModel):
    enabled: bool
    recovery_codes_left: int


_limit = Depends(rate_limit("2fa", 20, 60))


@router.get("", response_model=TwoFactorStatus)
def get_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return TwoFactorStatus(
        enabled=bool(user.totp_enabled),
        recovery_codes_left=two_factor_service.remaining_recovery_codes(db, user),
    )


@router.post("/setup", response_model=SetupResponse, dependencies=[_limit])
def setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        secret, uri = two_factor_service.begin_setup(db, user)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return SetupResponse(secret=secret, otpauth_uri=uri)


@router.post("/enable", response_model=RecoveryCodes, dependencies=[_limit])
def enable(body: CodeBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        codes = two_factor_service.enable(db, user, body.code)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return RecoveryCodes(recovery_codes=codes)


def _confirm(db: Session, user: User, code: str) -> None:
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-factor login is not on")
    try:
        two_factor_service.check(db, user, code)
    except two_factor_service.TwoFactorFailed as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_limit])
def disable(
    body: DisableBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    """Needs the password AND a current code, so a stolen session alone cannot switch it off."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect password")
    _confirm(db, user, body.code)
    two_factor_service.disable(db, user)


@router.post("/recovery-codes", response_model=RecoveryCodes, dependencies=[_limit])
def regenerate(
    body: CodeBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """New recovery codes (the old ones stop working). Needs a current code."""
    _confirm(db, user, body.code)
    return RecoveryCodes(recovery_codes=two_factor_service.new_recovery_codes(db, user))
