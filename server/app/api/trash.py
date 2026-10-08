"""GET/POST/DELETE /api/trash/* — list, restore and permanently delete trashed files."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.files import FileResponse
from app.schemas.trash import TrashListResponse
from app.services import trash_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="/api/trash", tags=["trash"])


@router.get("", response_model=TrashListResponse)
def list_trash(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's trashed files, most recently deleted first."""
    return TrashListResponse(files=trash_service.list_trash(db, current_user))


@router.post("/{file_id}/restore", response_model=FileResponse)
def restore(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Un-delete a file. Goes to the root if its folder is gone; renamed on a name clash."""
    try:
        return trash_service.restore_file(db, current_user, file_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Permanently delete a trashed file, its versions, and any now-unreferenced bytes."""
    try:
        trash_service.purge_file(db, current_user, file_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
