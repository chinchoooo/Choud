"""GET/POST /api/files/{id}/versions/* — version history, download, restore."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse as FastAPIFileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.file import File
from app.models.file_version import FileVersion
from app.models.user import User
from app.schemas.versions import VersionListResponse, VersionResponse
from app.services import file_service, version_service
from app.services.errors import ConflictError, NotFoundError, StorageError

router = APIRouter(prefix="/api/files", tags=["versions"])


def _to_response(version: FileVersion, file: File) -> VersionResponse:
    return VersionResponse(
        id=version.id,
        file_id=version.file_id,
        version_number=version.version_number,
        content_hash=version.content_hash,
        size=version.size,
        restored_from_version=version.restored_from_version,
        created_by=version.created_by,
        created_at=version.created_at,
        is_current=version.id == file.current_version_id,
    )


def _get_file(db: Session, user: User, file_id: uuid.UUID) -> File:
    """The caller's live file, or 404. Ownership is enforced in file_service."""
    try:
        return file_service.get_file(db, user, file_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{file_id}/versions", response_model=VersionListResponse)
def list_versions(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    file = _get_file(db, current_user, file_id)
    versions = version_service.list_versions(db, file)
    return VersionListResponse(
        file_id=file.id, versions=[_to_response(v, file) for v in versions]
    )


@router.get("/{file_id}/versions/{version_id}/download")
def download_version(
    file_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    file = _get_file(db, current_user, file_id)
    try:
        version = version_service.get_version(db, file, version_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        path = file_service.prepare_download(file, content_hash=version.content_hash)
    except StorageError as exc:
        # Same as the current-version download: never return nothing or
        # truncated data silently (Rule 5).
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FastAPIFileResponse(
        path,
        media_type=file.mime_type or "application/octet-stream",
        filename=file.name,
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.post(
    "/{file_id}/versions/{version_id}/restore",
    response_model=VersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def restore_version(
    file_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Make an old version current by appending a *new* version (history is kept)."""
    file = _get_file(db, current_user, file_id)
    try:
        new_version = version_service.restore_version(db, file, version_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.refresh(file)
    return _to_response(new_version, file)
