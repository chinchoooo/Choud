"""GET/POST/PATCH/DELETE /api/files/* — upload, download, rename, move,
delete, metadata.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi import File as FastAPIFile
from fastapi.responses import FileResponse as FastAPIFileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.api.library import decorate
from app.api.preconditions import conflict_http, parse_base_version
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.schemas.files import DirectoryListing, FileResponse, FileUpdate
from app.services import file_service

router = APIRouter(prefix="/api/files", tags=["files"])


def _not_found(exc: file_service.NotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("", response_model=DirectoryListing)
def list_directory(
    folder_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List a folder's contents (subfolders + files). Omit `folder_id` for root."""
    folder = None
    if folder_id is not None:
        try:
            folder = file_service.get_folder(db, current_user, folder_id)
        except file_service.NotFoundError as exc:
            raise _not_found(exc) from exc

    subfolders = file_service.list_subfolders(db, current_user, folder_id)
    files = file_service.list_files(db, current_user, folder_id)
    return DirectoryListing(
        folder=folder, subfolders=subfolders, files=decorate(db, current_user, files)
    )


@router.post(
    "/upload",
    dependencies=[Depends(rate_limit("upload", 600, 60))],
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload(
    file: UploadFile = FastAPIFile(...),
    folder_id: uuid.UUID | None = Form(default=None),
    name: str | None = Form(default=None),
    base_version_id: str | None = Form(default=None),
    taken_at: datetime | None = Form(default=None),
    modified_at: datetime | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file. Same name in the same folder = new version.

    `base_version_id` (optional) makes the upload conditional: the id of the
    version you started from, or `none` to require that nothing exists at that
    path yet. A mismatch is a structured `409` (see app/api/preconditions.py).
    """
    base, expect_new = parse_base_version(base_version_id)
    try:
        return await file_service.upload_file(
            db,
            current_user,
            file,
            folder_id,
            name,
            base_version_id=base,
            expect_new=expect_new,
            taken_at=taken_at,
            modified_at=modified_at,
        )
    except file_service.NotFoundError as exc:
        raise _not_found(exc) from exc
    except file_service.ConflictError as exc:
        raise conflict_http(exc) from exc
    except file_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except file_service.StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{file_id}", response_model=FileResponse)
def get_file(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return file_service.get_file(db, current_user, file_id)
    except file_service.NotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/{file_id}/download", dependencies=[Depends(rate_limit("download", 600, 60))])
def download(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        file = file_service.get_file(db, current_user, file_id)
    except file_service.NotFoundError as exc:
        raise _not_found(exc) from exc

    try:
        path = file_service.prepare_download(file)
    except file_service.StorageError as exc:
        # Metadata exists but the bytes couldn't be retrieved (missing,
        # corrupted, or the engine is unreachable) — surface a clean
        # error, never silently return nothing or truncated data (Rule 5).
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FastAPIFileResponse(
        path,
        media_type=file.mime_type or "application/octet-stream",
        filename=file.name,
        # The download is served from a throwaway staging copy (see
        # docs/storage.md — API routes never serve object-storage paths
        # directly); clean it up once the response has been sent.
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.patch("/{file_id}", response_model=FileResponse)
def update(
    file_id: uuid.UUID,
    body: FileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = body.model_dump(exclude_unset=True)
    try:
        return file_service.update_file(db, current_user, file_id, data)
    except file_service.NotFoundError as exc:
        raise _not_found(exc) from exc
    except file_service.ConflictError as exc:
        raise conflict_http(exc) from exc


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    file_id: uuid.UUID,
    base_version_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Move a file to the trash. With `base_version_id`, only if still on that version."""
    base, _ = parse_base_version(base_version_id)
    try:
        file_service.delete_file(db, current_user, file_id, base_version_id=base)
    except file_service.NotFoundError as exc:
        raise _not_found(exc) from exc
    except file_service.ConflictError as exc:
        raise conflict_http(exc) from exc
