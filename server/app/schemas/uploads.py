"""Pydantic request/response schemas for /api/uploads/*."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.folders import _validate_name


class UploadCreateRequest(BaseModel):
    """Starts a resumable upload session."""

    file_name: str
    file_size: int = Field(gt=0)
    chunk_size: int = Field(gt=0)
    folder_id: uuid.UUID | None = Field(default=None)
    # Optional client-claimed SHA-256 of the whole file, verified on
    # /complete (docs/architecture.md#11-chunk-storage). Omit it to skip
    # verification and just trust the reconstructed bytes.
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)
    # Optional precondition, applied when the upload completes: the id of the
    # version this file was based on, or "none" to require that nothing exists
    # at the path yet. Same meaning as on POST /api/files/upload.
    base_version_id: str | None = Field(default=None, max_length=36)
    # When the photo/video was taken, if known; becomes the file's `taken_at`.
    taken_at: datetime | None = Field(default=None)

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        return _validate_name(value)


class UploadSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    file_size: int
    chunk_size: int
    total_chunks: int
    status: str
    created_at: datetime
    expires_at: datetime


class UploadStatusResponse(UploadSessionResponse):
    """`GET /api/uploads/{id}` — session details plus what's still missing,
    so a resuming client knows exactly which chunks to (re)send."""

    received_chunk_indices: list[int]
    missing_chunk_indices: list[int]


class ChunkAckResponse(BaseModel):
    index: int
    received: bool
    received_count: int
    total_chunks: int


# `POST /api/uploads/{id}/complete` returns `app.schemas.files.FileResponse`
# directly — a completed chunked upload produces exactly the same thing a
# regular `POST /api/files/upload` does, so there's no separate response
# schema here; see `app/api/uploads.py`.
