"""GET /api/sync/snapshot, POST /api/sync/folders — endpoints for sync clients."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.sync import (
    EnsureFolderRequest,
    EnsureFolderResponse,
    SnapshotFileResponse,
    SnapshotFolderResponse,
    SnapshotResponse,
)
from app.services import sync_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/snapshot", response_model=SnapshotResponse)
def snapshot(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's whole live tree as flat lists with full paths.

    Trashed files are absent (to a sync client they are deleted). A file and a
    folder can share a name in the same parent on the server; clients must
    handle that collision, because a local filesystem can't hold both.
    """
    result = sync_service.build_snapshot(db, current_user)
    return SnapshotResponse(
        generated_at=datetime.now(UTC),
        folders=[SnapshotFolderResponse.model_validate(f) for f in result.folders],
        files=[SnapshotFileResponse.model_validate(f) for f in result.files],
    )


@router.post("/folders", response_model=EnsureFolderResponse)
def ensure_folder(
    body: EnsureFolderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create the folder path if missing (idempotent). Returns the leaf folder's id."""
    try:
        folder = sync_service.ensure_folder_path(db, current_user, body.path)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized = "/".join(sync_service.split_path(body.path))
    return EnsureFolderResponse(id=folder.id if folder else None, path=normalized)
