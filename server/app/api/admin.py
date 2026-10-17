"""/api/admin: a health-and-capacity view of the server, for the administrator."""

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.file import File
from app.models.file_text import FileText
from app.models.file_version import FileVersion
from app.models.upload import Upload
from app.models.user import User
from app.services import index_service, invite_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ServerStatus(BaseModel):
    disk_total_bytes: int
    disk_free_bytes: int
    users: int
    files: int
    versions: int
    logical_bytes: int
    stored_bytes: int
    uploads_in_progress: int
    index_pending: int
    index_failed: int
    registration_mode: str
    gc_delete_enabled: bool


@router.get("/server", response_model=ServerStatus)
def server_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not invite_service.is_admin(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the administrator can do this")
    settings = get_settings()
    root = Path(settings.storage_root)
    try:
        usage = shutil.disk_usage(root if root.exists() else root.anchor or ".")
        total, free = usage.total, usage.free
    except OSError:
        total = free = 0
    versions = db.execute(select(FileVersion.content_hash, FileVersion.size)).all()
    first: dict[str, int] = {}
    for row in versions:
        first.setdefault(row.content_hash, row.size)
    return ServerStatus(
        disk_total_bytes=total,
        disk_free_bytes=free,
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        files=db.scalar(select(func.count()).select_from(File).where(File.deleted_at.is_(None)))
        or 0,
        versions=len(versions),
        logical_bytes=sum(row.size for row in versions),
        stored_bytes=sum(first.values()),
        uploads_in_progress=db.scalar(
            select(func.count()).select_from(Upload).where(Upload.status == "pending")
        )
        or 0,
        index_pending=index_service.pending_count(db),
        index_failed=db.scalar(
            select(func.count()).select_from(FileText).where(FileText.status == "failed")
        )
        or 0,
        registration_mode=invite_service.mode(),
        gc_delete_enabled=settings.gc_delete_enabled,
    )
