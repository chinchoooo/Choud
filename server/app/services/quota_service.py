"""Storage quota (Phase 11): how much a user has stored, and whether a new upload fits."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion
from app.models.user import User
from app.services.errors import QuotaError


def usage_bytes(db: Session, user: User) -> int:
    """Bytes held by all of the user's file versions (live and trashed).

    Deliberately conservative: it counts every version at full size, even when
    deduplication shares one physical object between them, so the number the
    user sees can only over-estimate what the disk really holds.
    """
    stmt = (
        select(func.coalesce(func.sum(FileVersion.size), 0))
        .join(File, File.id == FileVersion.file_id)
        .where(File.owner_id == user.id)
    )
    return int(db.scalar(stmt) or 0)


def ensure_room(db: Session, user: User, incoming: int) -> None:
    """Raises `QuotaError` if storing `incoming` more bytes would exceed the quota."""
    quota = user.storage_quota
    if quota is None or quota <= 0:
        return
    used = usage_bytes(db, user)
    if used + incoming > quota:
        raise QuotaError(
            f"storage quota exceeded: {used + incoming} bytes needed, quota is {quota} bytes"
        )
