"""GET/POST/PATCH/DELETE /api/files/* — upload, download, rename, move,
delete, metadata.
"""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi import File as FastAPIFile
from fastapi.responses import FileResponse as FastAPIFileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.core.dependencies import get_current_user
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
    return DirectoryListing(folder=folder, subfolders=subfolders, files=files)


@router.post("/upload", response_model=FileResponse, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = FastAPIFile(...),
    folder_id: uuid.UUID | None = Form(default=None),
    name: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await file_service.upload_file(db, current_user, file, folder_id, name)
    except file_service.NotFoundError as exc:
        raise _not_found(exc) from exc
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


@router.get("/{file_id}/download")
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
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        file_service.delete_file(db, current_user, file_id)
    except file_service.NotFoundError as exc:
        raise _not_found(exc) from exc
