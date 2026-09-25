"""Pydantic request/response schemas for /api/folders/*."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be empty")
    if len(stripped) > 255:
        raise ValueError("name must be at most 255 characters")
    if "/" in stripped or "\\" in stripped:
        raise ValueError("name must not contain '/' or '\\\\'")
    if stripped in (".", ".."):
        raise ValueError("name must not be '.' or '..'")
    return stripped


class FolderCreate(BaseModel):
    name: str
    parent_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_name(value)


class FolderUpdate(BaseModel):
    """Rename and/or move a folder. Only fields explicitly sent are applied."""

    name: str | None = Field(default=None)
    parent_id: uuid.UUID | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_name(value)


class FolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    created_at: datetime
    updated_at: datetime
