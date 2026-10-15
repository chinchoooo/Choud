"""SQLAlchemy model for `activity` (Phase 11): a per-user log of what happened to files.

The file name is stored on the row (not just the id) so the log still reads
sensibly after a file is renamed, trashed or purged.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False, index=True
    )
    # uploaded | new_version | renamed | moved | trashed | restored | purged
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # No FK: a purged file's id must stay in the log.
    file_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
