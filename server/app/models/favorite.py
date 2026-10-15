"""SQLAlchemy model for `favorites` (Phase 11): a user starring a file."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class Favorite(Base):
    __tablename__ = "favorites"

    # Composite key: a user can star a file once.
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
