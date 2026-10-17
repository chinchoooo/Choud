"""SQLAlchemy model for `file_text`: the searchable text of a file's current content (Phase 14).

Derived data, like thumbnails: it can be thrown away and rebuilt at any time
(`python -m app.cli index --all`). `content_hash` says which bytes the text came from, so a changed
file is re-indexed and an unchanged one never is.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class FileText(Base):
    __tablename__ = "file_text"

    file_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # "ok" = text stored (possibly empty), "skipped" = a type or size that is not indexed,
    # "failed" = the file could not be read (recorded so it is not retried forever).
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
