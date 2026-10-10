"""POST/GET/DELETE /api/uploads/* — resumable chunked upload sessions.

See docs/architecture.md#10-chunked-uploads and docs/api.md. There's no
`uploads.py` in the initial skeleton (only the stub modules under
`app/models`/`app/schemas`), so this router is new — registered in
`app/main.py` alongside the others.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi import File as FastAPIFile
from sqlalchemy.orm import Session

from app.api.preconditions import conflict_http
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.files import FileResponse
from app.schemas.uploads import (
    ChunkAckResponse,
    UploadCreateRequest,
    UploadSessionResponse,
    UploadStatusResponse,
)
from app.services import upload_service

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


def _not_found(exc: upload_service.NotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _conflict(exc: upload_service.ConflictError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.post("", response_model=UploadSessionResponse, status_code=status.HTTP_201_CREATED)
def create_upload(
    body: UploadCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return upload_service.create_session(
            db,
            current_user,
            body.file_name,
            body.file_size,
            body.chunk_size,
            body.folder_id,
            body.expected_hash,
            body.base_version_id,
        )
    except upload_service.NotFoundError as exc:
        raise _not_found(exc) from exc
    except upload_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{upload_id}", response_model=UploadStatusResponse)
def get_upload_status(
    upload_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload = upload_service.get_status(db, current_user, upload_id)
    except upload_service.NotFoundError as exc:
        raise _not_found(exc) from exc

    received = upload.received_chunk_indices()
    missing = [i for i in range(upload.total_chunks) if i not in set(received)]
    return UploadStatusResponse(
        **UploadSessionResponse.model_validate(upload).model_dump(),
        received_chunk_indices=received,
        missing_chunk_indices=missing,
    )


@router.post("/{upload_id}/chunks/{index}", response_model=ChunkAckResponse)
async def upload_chunk(
    upload_id: uuid.UUID,
    index: int,
    chunk: UploadFile = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload = await upload_service.write_chunk(db, current_user, upload_id, index, chunk)
    except upload_service.NotFoundError as exc:
        raise _not_found(exc) from exc
    except upload_service.ConflictError as exc:
        raise _conflict(exc) from exc
    except upload_service.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except upload_service.StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    received_count = len(upload.received_chunk_indices())
    return ChunkAckResponse(
        index=index,
        received=True,
        received_count=received_count,
        total_chunks=upload.total_chunks,
    )


@router.post("/{upload_id}/complete", response_model=FileResponse)
def complete_upload(
    upload_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return upload_service.complete_upload(db, current_user, upload_id)
    except upload_service.NotFoundError as exc:
        raise _not_found(exc) from exc
    except upload_service.ConflictError as exc:
        # A structured body when it is a version conflict (see preconditions.py).
        raise conflict_http(exc) from exc
    except upload_service.StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def abandon_upload(
    upload_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Cancels an in-progress upload session (not in the original endpoint
    table in docs/api.md, but the natural way for a client to abort —
    added here the same way Phase 3 added a web login screen beyond its
    original spec where the goal genuinely needed it)."""
    try:
        upload_service.abandon_upload(db, current_user, upload_id)
    except upload_service.NotFoundError as exc:
        raise _not_found(exc) from exc
    except upload_service.StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
