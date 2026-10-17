"""The account's sign-in history and new-device detection."""

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.rate_limit import client_ip
from app.models.login_event import LoginEvent
from app.models.user import User

KEEP_DAYS = 365


def record_login(db: Session, user: User, request: Request, *, success: bool) -> LoginEvent:
    """Writes one history row. A success from an unseen (address, client) pair is flagged new."""
    ip = client_ip(request)[:64]
    agent = (request.headers.get("user-agent") or "")[:255]
    new_device = False
    if success:
        earlier = db.execute(
            select(LoginEvent.ip, LoginEvent.user_agent).where(
                LoginEvent.user_id == user.id, LoginEvent.success.is_(True)
            )
        ).all()
        # The very first login is not "new": there is nothing to compare it with.
        new_device = bool(earlier) and (ip, agent) not in {
            (row.ip, row.user_agent) for row in earlier
        }
    event = LoginEvent(
        user_id=user.id,
        at=datetime.now(UTC),  # microseconds: same-second events keep their order
        ip=ip,
        user_agent=agent,
        success=success,
        new_device=new_device,
    )
    db.add(event)
    db.execute(
        delete(LoginEvent).where(
            LoginEvent.user_id == user.id,
            LoginEvent.at < datetime.now(UTC) - timedelta(days=KEEP_DAYS),
        )
    )
    db.commit()
    return event


def recent_events(db: Session, user: User, limit: int = 50) -> list[LoginEvent]:
    return list(
        db.execute(
            select(LoginEvent)
            .where(LoginEvent.user_id == user.id)
            .order_by(LoginEvent.at.desc())
            .limit(limit)
        ).scalars()
    )
