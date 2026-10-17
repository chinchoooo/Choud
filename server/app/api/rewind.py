"""/api/rewind: browse and restore files as they were at an earlier time."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services import rewind_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="/api/rewind", tags=["rewind"])


def _moment(value: datetime) -> datetime:
    when = value if value.tzinfo else value.replace(tzinfo=UTC)
    if when > datetime.now(UTC):
        raise HTTPException(status_code=422, detail="choose a time in the past")
    return when


class PastFileOut(BaseModel):
    id: uuid.UUID
    name: str
    mime_type: str | None
    size: int
    version_number: int
    version_at: datetime
    changed: bool  # today's content differs from then
    trashed: bool  # it is in the trash today


class PastFolderOut(BaseModel):
    id: uuid.UUID
    name: str


class BrowseResponse(BaseModel):
    at: datetime
    folder_id: uuid.UUID | None
    folder_name: str | None
    folders: list[PastFolderOut]
    files: list[PastFileOut]


class RestoreFileBody(BaseModel):
    file_id: uuid.UUID
    at: datetime


class RestoreTreeBody(BaseModel):
    folder_id: uuid.UUID | None = None
    at: datetime
    dry_run: bool = True  # preview first: nothing changes unless this is false


class ReportOut(BaseModel):
    dry_run: bool = False
    restored_content: int
    undeleted: int
    unchanged: int
    newer_untouched: int
    files: list[str]


def _report(report: rewind_service.RestoreReport, dry_run: bool) -> ReportOut:
    return ReportOut(
        dry_run=dry_run,
        restored_content=report.restored_content,
        undeleted=report.undeleted,
        unchanged=report.unchanged,
        newer_untouched=report.newer_untouched,
        files=report.files,
    )


@router.get("/browse", response_model=BrowseResponse)
def browse(
    at: datetime = Query(...),
    folder_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    when = _moment(at)
    try:
        folder, folders, files = rewind_service.browse(db, user, when, folder_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BrowseResponse(
        at=when,
        folder_id=folder.id if folder else None,
        folder_name=folder.name if folder else None,
        folders=[PastFolderOut(id=f.id, name=f.name) for f in folders],
        files=[
            PastFileOut(
                id=p.file.id,
                name=p.file.name,
                mime_type=p.file.mime_type,
                size=p.version.size,
                version_number=p.version.version_number,
                version_at=p.version.created_at,
                changed=p.changed,
                trashed=p.trashed,
            )
            for p in files
        ],
    )


@router.post("/restore-file", response_model=ReportOut)
def restore_file(
    body: RestoreFileBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        report = rewind_service.restore_file(db, user, body.file_id, _moment(body.at))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _report(report, dry_run=False)


@router.post("/restore-tree", response_model=ReportOut)
def restore_tree(
    body: RestoreTreeBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Preview (default) or perform putting a folder tree back to how it was."""
    try:
        report = rewind_service.restore_tree(
            db, user, _moment(body.at), body.folder_id, dry_run=body.dry_run
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _report(report, body.dry_run)
