"""/api/insights: where your space went, and (explicitly) giving some of it back."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services import insights_service

router = APIRouter(prefix="/api/insights", tags=["insights"])


class BigFile(BaseModel):
    id: uuid.UUID
    name: str
    size: int


class DuplicateFile(BaseModel):
    id: uuid.UUID
    name: str


class DuplicateGroup(BaseModel):
    size: int
    copies: int
    files: list[DuplicateFile]


class SpaceResponse(BaseModel):
    quota_bytes: int
    logical_bytes: int
    stored_bytes: int
    dedup_saved_bytes: int
    current_bytes: int
    trash_bytes: int
    history_bytes: int
    by_type: dict[str, int]
    biggest: list[BigFile]
    duplicates: list[DuplicateGroup]
    duplicate_files: int


class PruneBody(BaseModel):
    keep: int = Field(default=5, ge=1, le=100)
    dry_run: bool = True  # nothing is deleted unless this is explicitly false


class PruneResponse(BaseModel):
    dry_run: bool
    versions_removed: int
    bytes_freed: int
    files_affected: int


@router.get("/space", response_model=SpaceResponse)
def space(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = insights_service.space_report(db, user)
    return SpaceResponse(quota_bytes=user.storage_quota, **report.__dict__)


@router.post("/prune-versions", response_model=PruneResponse)
def prune(body: PruneBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Keep only the newest `keep` versions of each file (the current one always stays).

    Defaults to a preview. Pruned versions cannot be restored or rewound to afterwards.
    """
    report = insights_service.prune_versions(db, user, body.keep, dry_run=body.dry_run)
    return PruneResponse(dry_run=body.dry_run, **report.__dict__)
