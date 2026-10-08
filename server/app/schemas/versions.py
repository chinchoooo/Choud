"""Pydantic response schemas for /api/files/{id}/versions/*."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class VersionResponse(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    version_number: int
    content_hash: str
    size: int
    # Set when this version was created by restoring an older one: the number
    # of the version whose content it copies. None for a normal upload.
    restored_from_version: int | None
    created_by: uuid.UUID
    created_at: datetime
    # True for the version the file currently serves.
    is_current: bool


class VersionListResponse(BaseModel):
    """A file's history, newest first."""

    file_id: uuid.UUID
    versions: list[VersionResponse]
