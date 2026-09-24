"""SQLAlchemy model for `files`. See docs/architecture.md#database-design."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False, index=True
    )
    # NULL folder_id means this file lives at the root of the owner's tree.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("folders.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Since Phase 4, bytes live in the C++ engine's content-addressable
    # store, keyed by SHA-256 hash (see app/services/file_service.py and
    # docs/storage.md). `content_hash` is always populated by
    # `upload_file()` now; it stays nullable at the DB level rather than
    # adding a migration to tighten it, since nothing has ever shipped
    # with Phase-3-era rows that lack it.
    #
    # `storage_key` predates content-addressing (Phase 3's server-generated
    # per-file id); it's kept as "the key used to locate bytes in the
    # storage backend" and is now always equal to `content_hash`.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)

    # Points at the current `file_versions` row once Phase 6 (Versioning)
    # adds that table. No FK constraint yet — the referenced table doesn't
    # exist until then; Phase 6 adds it via its own migration.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    # Soft delete / trash (see docs/architecture.md#13-trash). NULL means
    # not deleted.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"File(id={self.id!r}, name={self.name!r})"
