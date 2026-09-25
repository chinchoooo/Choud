"""Pydantic request/response schemas for /api/files/*."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.folders import FolderResponse, _validate_name


class FileUpdate(BaseModel):
    """Rename and/or move a file. Only fields explicitly sent are applied.

    To move a file to the root, send `{"folder_id": null}` explicitly —
    the service layer only touches fields present in the request body
    (`model_dump(exclude_unset=True)`), so an omitted field is left alone.
    """

    name: str | None = Field(default=None)
    folder_id: uuid.UUID | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_name(value)


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    folder_id: uuid.UUID | None
    name: str
    mime_type: str | None
    size: int
    content_hash: str | None
    created_at: datetime
    updated_at: datetime


class DirectoryListing(BaseModel):
    """Response for `GET /api/files?folder_id=...` — one folder's contents."""

    folder: FolderResponse | None
    subfolders: list[FolderResponse]
    files: list[FileResponse]


class SearchResponse(BaseModel):
    folders: list[FolderResponse]
    files: list[FileResponse]
