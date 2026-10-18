"""POST /api/archive/zip: download a selection of files and folders as one .zip."""

import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse as FastAPIFileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.services import archive_service, file_service

router = APIRouter(prefix="/api/archive", tags=["archive"])


class ZipRequest(BaseModel):
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    folder_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


def _download_name(db: Session, user: User, body: ZipRequest) -> str:
    if len(body.folder_ids) == 1 and not body.file_ids:
        name = file_service.get_folder(db, user, body.folder_ids[0]).name
    else:
        name = f"choud-{date.today().isoformat()}"
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)[:100] + ".zip"


@router.post("/zip", dependencies=[Depends(rate_limit("zip", 20, 60))])
def zip_download(
    body: ZipRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        name = _download_name(db, user, body)
        path, _ = archive_service.build_zip(db, user, body.file_ids, body.folder_ids)
    except archive_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except file_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except archive_service.PayloadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except file_service.StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FastAPIFileResponse(
        path,
        media_type="application/zip",
        filename=name,
        background=BackgroundTask(path.unlink, missing_ok=True),
    )
