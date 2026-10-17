"""Who may register, and the invite codes that let more people in (Phase 11b)."""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.invite import Invite
from app.models.user import User
from app.services.errors import NotFoundError

MODES = ("invite", "open", "closed")


class RegistrationClosed(Exception):
    """Registration is not allowed for this request (no/invalid invite, or mode is closed)."""


def mode() -> str:
    value = get_settings().registration_mode.lower()
    return value if value in MODES else "invite"


def user_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(User)).scalar_one()


def is_admin(db: Session, user: User) -> bool:
    """The administrator is the oldest account (the one that set the server up)."""
    first = db.execute(select(User).order_by(User.created_at, User.username).limit(1)).scalar()
    return first is not None and first.id == user.id


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _usable(db: Session, code: str) -> Invite | None:
    invite = db.execute(select(Invite).where(Invite.code == code)).scalar_one_or_none()
    if invite is None or invite.used_at is not None:
        return None
    if invite.expires_at is not None and _aware(invite.expires_at) <= datetime.now(UTC):
        return None
    return invite


def registration_info(db: Session) -> dict:
    first = user_count(db) == 0
    current = mode()
    return {
        "mode": current,
        "open": current == "open" or first,
        "invite_required": current == "invite" and not first,
        "first_account": first,
    }


def authorize_registration(db: Session, invite_code: str | None) -> Invite | None:
    """Raises RegistrationClosed unless this signup is allowed. Returns the invite it will use."""
    if user_count(db) == 0:  # the very first account sets the server up
        return None
    current = mode()
    if current == "open":
        return None
    if current == "closed":
        raise RegistrationClosed("Registration is closed on this server.")
    invite = _usable(db, invite_code.strip()) if invite_code else None
    if invite is None:
        raise RegistrationClosed("A valid invite code is needed to create an account.")
    return invite


def redeem(db: Session, invite: Invite, user: User) -> None:
    invite.used_by = user.id
    invite.used_at = datetime.now(UTC)
    if invite.storage_quota:
        user.storage_quota = invite.storage_quota


def create_invite(
    db: Session,
    admin: User,
    note: str | None = None,
    expires_in_hours: int | None = 24 * 7,
    storage_quota: int | None = None,
) -> Invite:
    expires = datetime.now(UTC) + timedelta(hours=expires_in_hours) if expires_in_hours else None
    invite = Invite(
        code=secrets.token_urlsafe(12),
        created_by=admin.id,
        note=note or None,
        storage_quota=storage_quota,
        expires_at=expires,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def list_invites(db: Session) -> list[Invite]:
    return list(db.execute(select(Invite).order_by(Invite.created_at.desc())).scalars())


def delete_invite(db: Session, invite_id) -> None:
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise NotFoundError("invite not found")
    db.delete(invite)
    db.commit()
