"""SQLAlchemy model for `file_versions`. See docs/architecture.md#12-versioning.

Every content change to a file (a same-name re-upload, or restoring an old
version) appends one row here. Rows are never edited or removed while the
file lives — history is append-only. They disappear only when the file is
permanently purged from the trash (see `version_service.purge_file`).

`files.content_hash` / `files.size` always mirror the version that
`files.current_version_id` points at, so the hot read paths (listing,
download, search) never have to join this table.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class FileVersion(Base):
    __tablename__ = "file_versions"
    __table_args__ = (
        UniqueConstraint("file_id", "version_number", name="uq_file_versions_file_id_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("files.id"), nullable=False, index=True
    )
    # 1-based, strictly increasing per file. A restore creates a *new* number.
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # When this version was restored from an older one, the number of the
    # version whose content it copies; NULL for a normal upload.
    restored_from_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"FileVersion(file_id={self.file_id!r}, version_number={self.version_number!r})"
