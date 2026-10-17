"""Two-factor login: setting it up, checking a code at login, recovery codes (Phase 13)."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import totp
from app.models.recovery_code import RecoveryCode
from app.models.user import User
from app.services.errors import ConflictError, ValidationError

RECOVERY_CODE_COUNT = 10
MAX_FAILURES = 5
LOCK_MINUTES = 15
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (i, l, o, 0, 1)


class TwoFactorFailed(Exception):
    """The code was wrong, already used, or too many wrong codes were tried recently."""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().lower().replace(" ", "").encode()).hexdigest()


def _new_recovery_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def begin_setup(db: Session, user: User) -> tuple[str, str]:
    """A fresh secret (not active yet) and the otpauth:// link for the QR code."""
    if user.totp_enabled:
        raise ConflictError("Two-factor login is already on")
    user.totp_secret = totp.new_secret()
    db.commit()
    return user.totp_secret, totp.otpauth_uri(user.totp_secret, user.email)


def _issue_recovery_codes(db: Session, user: User) -> list[str]:
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=_hash(code)))
    return codes


def enable(db: Session, user: User, code: str) -> list[str]:
    """Turn it on once the user proves their app shows the right code. Returns recovery codes."""
    if user.totp_enabled:
        raise ConflictError("Two-factor login is already on")
    if not user.totp_secret:
        raise ValidationError("Start the setup first")
    step = totp.verify(user.totp_secret, code)
    if step is None:
        raise ValidationError("That code is not right. Check the time on your phone and try again.")
    user.totp_enabled = True
    user.totp_last_step = step
    user.totp_failures = 0
    codes = _issue_recovery_codes(db, user)
    db.commit()
    return codes


def check(db: Session, user: User, code: str) -> None:
    """Accept an authenticator code or an unused recovery code; otherwise raise TwoFactorFailed.

    Five wrong tries lock further attempts for 15 minutes, so the 6 digits cannot be ground out.
    """
    now = datetime.now(UTC)
    if user.totp_locked_until is not None and _aware(user.totp_locked_until) > now:
        raise TwoFactorFailed("Too many wrong codes. Try again in a few minutes.")

    code = (code or "").strip()
    ok = False
    if user.totp_secret:
        step = totp.verify(user.totp_secret, code, user.totp_last_step)
        if step is not None:
            user.totp_last_step = step
            ok = True
    if not ok:
        stored = db.execute(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_hash == _hash(code),
                RecoveryCode.used_at.is_(None),
            )
        ).scalar_one_or_none()
        if stored is not None:
            stored.used_at = now
            ok = True

    if ok:
        user.totp_failures = 0
        user.totp_locked_until = None
        db.commit()
        return
    user.totp_failures = (user.totp_failures or 0) + 1
    if user.totp_failures >= MAX_FAILURES:
        user.totp_locked_until = now + timedelta(minutes=LOCK_MINUTES)
        user.totp_failures = 0
    db.commit()
    raise TwoFactorFailed("That code is not right.")


def disable(db: Session, user: User) -> None:
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_last_step = None
    user.totp_failures = 0
    user.totp_locked_until = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    db.commit()


def new_recovery_codes(db: Session, user: User) -> list[str]:
    codes = _issue_recovery_codes(db, user)
    db.commit()
    return codes


def remaining_recovery_codes(db: Session, user: User) -> int:
    rows = db.execute(
        select(RecoveryCode.id).where(
            RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
        )
    ).all()
    return len(rows)
