"""SQLAlchemy model for `uploads`. See docs/architecture.md#database-design."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import GUID


class Upload(Base):
    """A resumable chunked-upload session (Phase 5, docs/architecture.md#10-chunked-uploads).

    Deviations from the `uploads` table sketched in
    docs/architecture.md#database-design, both documented here rather than
    silently diverging:

    - `folder_id` is new. The diagram doesn't have it, but *something* has
      to remember where the finished file gets placed once the session
      completes (`POST /api/files/upload` gets this as a form field
      instead; chunked uploads have no equivalent per-request slot).
    - `received_chunks` is a comma-separated list of received chunk
      indices (e.g. `"0,2,3"`), not a bare count — a resuming client needs
      to know *which* chunks are still missing, not just how many arrived
      (`docs/api.md`'s `GET /api/uploads/{id}` status endpoint is what
      exposes this). The engine's on-disk chunk directory is the real
      source of truth for what's actually stored (see
      `engine::chunks::ChunkStore`); this column is a fast, queryable
      mirror of it that avoids asking the engine on every status check.
    """

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False, index=True
    )
    # NULL means the finished file goes to the root of the owner's tree.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("folders.id"), nullable=True
    )

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Carried to the file when the upload completes (see File.taken_at / File.modified_at).
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The size the client *claims* the finished file will be. Not trusted
    # for anything beyond computing `total_chunks` up front — the file
    # row created on completion uses the actual reconstructed size, which
    # is what the engine measured, not what the client declared.
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    received_chunks: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Optional client-claimed SHA-256 of the whole file, verified against
    # what the engine actually reconstructs on `/complete`
    # (docs/architecture.md#11-chunk-storage). NULL means "don't verify,
    # just trust whatever bytes the chunks reconstruct to" — the content
    # hash is still always computed either way.
    expected_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Optional precondition carried to completion, same meaning as the
    # `base_version_id` of a plain upload (see app/api/preconditions.py): a
    # version id the client started from, or "none" to require that no live
    # file exists at the path. Stored as the raw string the client sent, since
    # it is only interpreted when the session completes. NULL = unconditional.
    base_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # "pending" | "completed" | "aborted" | "expired". Kept as a plain
    # string rather than a DB enum (Rule 2: no unnecessary
    # abstraction/dependency for a handful of values only this module
    # ever writes).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Upload(id={self.id!r}, file_name={self.file_name!r}, status={self.status!r})"

    # --- received_chunks helpers -----------------------------------------

    def received_chunk_indices(self) -> list[int]:
        if not self.received_chunks:
            return []
        return [int(i) for i in self.received_chunks.split(",")]

    def mark_chunk_received(self, index: int) -> None:
        indices = set(self.received_chunk_indices())
        indices.add(index)
        self.received_chunks = ",".join(str(i) for i in sorted(indices))
