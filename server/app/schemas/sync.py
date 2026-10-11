"""Pydantic schemas for /api/sync/*."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SnapshotFolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    # '/'-separated, relative to the root, no leading slash.
    path: str


class SnapshotFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    folder_id: uuid.UUID | None
    name: str
    path: str
    size: int
    content_hash: str | None
    # The server-side version pointer. A client remembers this after a sync and
    # sends it back as `base_version_id` to detect that somebody else changed
    # the file in the meantime.
    version_id: uuid.UUID | None
    updated_at: datetime


class SnapshotResponse(BaseModel):
    generated_at: datetime
    folders: list[SnapshotFolderResponse]
    files: list[SnapshotFileResponse]


class EnsureFolderRequest(BaseModel):
    # Relative path such as "Research/2026/notes". Empty means the root.
    path: str


class EnsureFolderResponse(BaseModel):
    # null for the root.
    id: uuid.UUID | None
    path: str
