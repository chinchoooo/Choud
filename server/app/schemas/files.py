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
    # Dates reported by the device that holds the original (used to fix up files that were
    # backed up before the server recorded them).
    taken_at: datetime | None = Field(default=None)
    modified_at: datetime | None = Field(default=None)

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
    # The version this file is currently on. A sync client remembers it after an
    # upload and sends it back as `base_version_id` to detect concurrent edits.
    current_version_id: uuid.UUID | None = None
    # When a photo/video was taken, if the uploading client knew.
    taken_at: datetime | None = None
    # The uploading device's own last-modified time; clients show this as the file's date.
    modified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Filled in by the routes that know the viewer's favorites / the folder tree.
    is_favorite: bool = False
    folder_path: str | None = None


class DirectoryListing(BaseModel):
    """Response for `GET /api/files?folder_id=...` — one folder's contents."""

    folder: FolderResponse | None
    subfolders: list[FolderResponse]
    files: list[FileResponse]


class SearchResponse(BaseModel):
    folders: list[FolderResponse]
    files: list[FileResponse]
