"""Per-user activity log (Phase 11). Callers add rows inside their own transaction."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity


def record(
    db: Session,
    user_id: uuid.UUID,
    action: str,
    *,
    file_id: uuid.UUID | None,
    file_name: str,
    detail: str | None = None,
) -> None:
    """Adds an activity row (no flush/commit: it lives and dies with the caller's change)."""
    db.add(
        Activity(
            user_id=user_id,
            action=action,
            file_id=file_id,
            file_name=file_name[:255],
            detail=(detail[:500] if detail else None),
        )
    )


def list_recent(db: Session, user_id: uuid.UUID, limit: int = 50) -> list[Activity]:
    stmt = (
        select(Activity)
        .where(Activity.user_id == user_id)
        .order_by(Activity.created_at.desc(), Activity.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))
