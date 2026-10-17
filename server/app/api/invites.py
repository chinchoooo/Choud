"""/api/invites: the administrator makes single-use signup codes (Phase 11b)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services import invite_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="/api/invites", tags=["invites"])


class InviteCreate(BaseModel):
    note: str | None = Field(default=None, max_length=255)
    expires_in_hours: int | None = Field(default=24 * 7, ge=1, le=24 * 365)
    storage_quota_bytes: int | None = Field(default=None, ge=1)


class InviteResponse(BaseModel):
    id: uuid.UUID
    code: str
    note: str | None
    storage_quota: int | None
    expires_at: datetime | None
    used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _admin(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if not invite_service.is_admin(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the administrator can do this")
    return user


@router.post("", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create(body: InviteCreate, admin: User = Depends(_admin), db: Session = Depends(get_db)):
    return invite_service.create_invite(
        db, admin, body.note, body.expires_in_hours, body.storage_quota_bytes
    )


@router.get("", response_model=list[InviteResponse])
def list_all(_: User = Depends(_admin), db: Session = Depends(get_db)):
    return invite_service.list_invites(db)


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(invite_id: uuid.UUID, _: User = Depends(_admin), db: Session = Depends(get_db)) -> None:
    try:
        invite_service.delete_invite(db, invite_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
