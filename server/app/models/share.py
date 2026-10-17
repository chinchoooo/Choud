"""SQLAlchemy model for `shares`: public links to a file or a folder (Phase 12).

A share is a bearer link (`/s/<token>`): whoever holds the link can see what it points at, until
it expires or is revoked, optionally behind a password. The token is stored as-is (not hashed) so
the owner can copy the link again later; it is 256 bits of randomness, and revoking the row kills
the link at once.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class Share(Base):
    __tablename__ = "shares"
    __table_args__ = (
        # Exactly one target: a file or a folder.
        CheckConstraint(
            "(file_id IS NOT NULL AND folder_id IS NULL) "
            "OR (file_id IS NULL AND folder_id IS NOT NULL)",
            name="ck_shares_one_target",
        ),
        CheckConstraint("permission IN ('view', 'edit')", name="ck_shares_permission"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("files.id", ondelete="CASCADE"), nullable=True, index=True
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "view" = look and download. "edit" = also add files, make folders, rename and trash inside a
    # shared folder (or replace a shared file with a new version). Nothing is ever hard-deleted.
    permission: Mapped[str] = mapped_column(
        String(8), nullable=False, default="view", server_default="view"
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
