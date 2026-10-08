"""Pydantic response schemas for /api/trash/*."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrashedFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    # Where it will be restored to. May be null (root), and is replaced by the
    # root at restore time if the folder has since been deleted.
    folder_id: uuid.UUID | None
    mime_type: str | None
    size: int
    content_hash: str | None
    deleted_at: datetime


class TrashListResponse(BaseModel):
    files: list[TrashedFileResponse]
