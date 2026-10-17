"""Pydantic schemas for /api/shares (public links, Phase 12)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_EXPIRY_HOURS = 24 * 365


class ShareCreate(BaseModel):
    """Create a public link to exactly one file or one folder."""

    file_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    # None = the link never expires on its own (it can still be revoked).
    expires_in_hours: int | None = Field(default=None, ge=1, le=MAX_EXPIRY_HOURS)
    # None = no password. Anyone with the link can open it, so a password is the second lock.
    password: str | None = Field(default=None, min_length=4, max_length=128)
    label: str | None = Field(default=None, max_length=255)
    # "view": look and download. "edit": also add files, make folders, rename, delete.
    # "drop" = a file request: visitors can only send files into a folder.
    permission: Literal["view", "edit", "drop"] = "view"
    # The link dies after this many downloads (a one-time link is 1). None = unlimited.
    max_downloads: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def exactly_one_target(self) -> "ShareCreate":
        if (self.file_id is None) == (self.folder_id is None):
            raise ValueError("give exactly one of file_id or folder_id")
        if self.permission == "drop" and self.folder_id is None:
            raise ValueError("a file request (drop) link needs a folder")
        return self


class ShareUpdate(BaseModel):
    """Change a link. Only fields that are sent are applied; `null` clears password / expiry."""

    label: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=4, max_length=128)
    expires_in_hours: int | None = Field(default=None, ge=1, le=MAX_EXPIRY_HOURS)
    permission: Literal["view", "edit", "drop"] | None = None
    max_downloads: int | None = Field(default=None, ge=1, le=1_000_000)


class ShareResponse(BaseModel):
    id: uuid.UUID
    kind: str  # "file" | "folder"
    target_id: uuid.UUID
    target_name: str
    token: str
    # Path on this server, e.g. /s/AbC...; the client adds its own origin.
    url_path: str
    label: str | None
    has_password: bool
    permission: str
    max_downloads: int | None
    expires_at: datetime | None
    created_at: datetime
    download_count: int
    last_accessed_at: datetime | None
    active: bool
