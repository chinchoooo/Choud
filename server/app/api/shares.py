"""POST/GET/PATCH/DELETE /api/shares: manage your public links (Phase 12).

The public side (`/s/<token>`) lives in `public_shares.py`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.shares import ShareCreate, ShareResponse, ShareUpdate
from app.services import share_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="/api/shares", tags=["shares"])


@router.post("", response_model=ShareResponse, status_code=status.HTTP_201_CREATED)
def create(
    body: ShareCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        share = share_service.create_share(
            db,
            current_user,
            file_id=body.file_id,
            folder_id=body.folder_id,
            expires_in_hours=body.expires_in_hours,
            password=body.password,
            label=body.label,
            permission=body.permission,
            max_downloads=body.max_downloads,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return share_service.describe(db, share)


@router.get("", response_model=list[ShareResponse])
def list_mine(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [share_service.describe(db, s) for s in share_service.list_shares(db, current_user)]


@router.patch("/{share_id}", response_model=ShareResponse)
def update(
    share_id: uuid.UUID,
    body: ShareUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        share = share_service.update_share(
            db, current_user, share_id, body.model_dump(exclude_unset=True)
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return share_service.describe(db, share)


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke(
    share_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        share_service.revoke_share(db, current_user, share_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
