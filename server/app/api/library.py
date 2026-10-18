"""Library views over a user's files (Phase 11): recents, photos, favorites,
usage and activity. All owner-scoped."""

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.activity import Activity
from app.models.favorite import Favorite
from app.models.file import File
from app.models.folder import Folder
from app.models.user import User
from app.schemas.files import FileResponse
from app.services import activity_service, dates_service, file_service, quota_service

router = APIRouter(prefix="/api/library", tags=["library"])


def _folder_paths(db: Session, user: User) -> dict[uuid.UUID, str]:
    """Full path of every folder the user owns, e.g. {id: 'Phone Backups/Pixel/Camera'}."""
    rows = db.execute(
        select(Folder.id, Folder.name, Folder.parent_id).where(Folder.owner_id == user.id)
    ).all()
    by_id = {r.id: (r.name, r.parent_id) for r in rows}
    paths: dict[uuid.UUID, str] = {}
    for folder_id in by_id:
        parts: list[str] = []
        seen: set[uuid.UUID] = set()
        cursor: uuid.UUID | None = folder_id
        while cursor is not None and cursor in by_id and cursor not in seen:
            seen.add(cursor)
            name, cursor = by_id[cursor]
            parts.append(name)
        paths[folder_id] = "/".join(reversed(parts))
    return paths


def decorate(db: Session, user: User, files: list[File]) -> list[FileResponse]:
    """Turns files into responses with `is_favorite` and `folder_path` filled in."""
    ids = [f.id for f in files]
    favorite_ids: set[uuid.UUID] = set()
    if ids:
        favorite_ids = set(
            db.scalars(
                select(Favorite.file_id).where(
                    Favorite.user_id == user.id, Favorite.file_id.in_(ids)
                )
            )
        )
    paths = _folder_paths(db, user) if files else {}
    out = []
    for f in files:
        item = FileResponse.model_validate(f)
        item.is_favorite = f.id in favorite_ids
        item.folder_path = paths.get(f.folder_id, "") if f.folder_id else ""
        out.append(item)
    return out


class FixDatesBody(BaseModel):
    dry_run: bool = True  # preview first: nothing changes unless this is false


class FixDatesReport(BaseModel):
    dry_run: bool
    checked: int
    fixed: int
    from_name: int
    from_exif: int
    no_date_found: int
    examples: list[str]


@router.post("/fix-dates", response_model=FixDatesReport)
def fix_dates(
    body: FixDatesBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Give photos and videos that were uploaded without a date the real one, from the file name
    (IMG_20250206_160717.jpg and the like) or the photo's own EXIF data. Previews by default."""
    report = dates_service.fix_dates(db, current_user, dry_run=body.dry_run)
    return FixDatesReport(
        dry_run=body.dry_run,
        checked=report.checked,
        fixed=report.fixed,
        from_name=report.from_name,
        from_exif=report.from_exif,
        no_date_found=report.no_date_found,
        examples=report.examples,
    )


class MemoryGroup(BaseModel):
    year: int
    years_ago: int
    files: list[FileResponse]


@router.get("/memories", response_model=list[MemoryGroup])
def memories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Photos and videos from this day (month and day) in earlier years, newest year first."""
    today = datetime.now().date()
    rows = db.execute(
        select(File.id, File.taken_at, File.modified_at, File.created_at).where(
            File.owner_id == current_user.id,
            File.deleted_at.is_(None),
            or_(File.mime_type.like("image/%"), File.mime_type.like("video/%")),
        )
    ).all()
    by_year: dict[int, list[uuid.UUID]] = {}
    for row in rows:
        when = row.taken_at or row.modified_at or row.created_at
        if when and when.month == today.month and when.day == today.day and when.year < today.year:
            by_year.setdefault(when.year, []).append(row.id)
    groups = []
    for year in sorted(by_year, reverse=True)[:10]:
        files = list(
            db.scalars(select(File).where(File.id.in_(by_year[year][:60])).order_by(File.name))
        )
        groups.append(
            MemoryGroup(
                year=year,
                years_ago=today.year - year,
                files=decorate(db, current_user, files),
            )
        )
    return groups


@router.get("/recent", response_model=list[FileResponse])
def recent(
    limit: int = Query(default=30, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Most recently added or changed files."""
    files = list(
        db.scalars(
            select(File)
            .where(File.owner_id == current_user.id, File.deleted_at.is_(None))
            .order_by(File.updated_at.desc(), File.id)
            .limit(limit)
        )
    )
    return decorate(db, current_user, files)


class PhotoPage(BaseModel):
    items: list[FileResponse]
    total: int
    offset: int
    limit: int


@router.get("/photos", response_model=PhotoPage)
def photos(
    kind: str = Query(default="all", pattern="^(all|image|video)$"),
    limit: int = Query(default=120, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Photos and videos from every folder, newest first (by taken_at, else upload time)."""
    if kind == "image":
        media = File.mime_type.like("image/%")
    elif kind == "video":
        media = File.mime_type.like("video/%")
    else:
        media = or_(File.mime_type.like("image/%"), File.mime_type.like("video/%"))
    where = (File.owner_id == current_user.id, File.deleted_at.is_(None), media)
    total = db.scalar(select(func.count()).select_from(File).where(*where)) or 0
    files = list(
        db.scalars(
            select(File)
            .where(*where)
            .order_by(
                func.coalesce(File.taken_at, File.modified_at, File.created_at).desc(), File.id
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return PhotoPage(
        items=decorate(db, current_user, files), total=total, offset=offset, limit=limit
    )


INDEX_COLUMNS = [
    "id",
    "name",
    "mime",
    "size",
    "taken",
    "modified",
    "created",
    "hash",
    "thumbhash",
    "folder_path",
]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


class LibraryIndex(BaseModel):
    cursor: str | None
    full: bool
    columns: list[str]
    rows: list[list]
    removed: list[str]
    favorites: list[str]


@router.get("/index", response_model=LibraryIndex)
def library_index(
    request: Request,
    response: Response,
    since: str | None = Query(default=None, max_length=64),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The whole photo and video library as compact rows, so a phone can keep it in a local
    database and paint any month instantly, offline.

    Without `since` it is every live photo and video. With `since` (a `cursor` from an earlier
    answer) it is only what changed after that: `rows` are new or changed files, `removed` are ids
    that were trashed. `favorites` is always the full list of starred ids (it is small). Answers
    carry an ETag, so asking again when nothing changed costs one tiny 304.
    """
    media = or_(File.mime_type.like("image/%"), File.mime_type.like("video/%"))
    base = (File.owner_id == current_user.id, media)
    newest = db.scalar(select(func.max(File.updated_at)).where(*base))
    favorite_ids = sorted(
        str(i)
        for i in db.scalars(select(Favorite.file_id).where(Favorite.user_id == current_user.id))
    )
    since_at: datetime | None = None
    if since:
        try:
            since_at = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="since must be an ISO date") from exc
    cursor = _iso(newest)
    count = db.scalar(select(func.count()).select_from(File).where(*base)) or 0
    # The ETag names the library's STATE (not the question): a client that applied state S and asks
    # "anything since S?" with that ETag gets a bodyless 304 while nothing has changed.
    etag_source = f"{cursor}|{count}|{','.join(favorite_ids)}"
    etag = '"' + hashlib.sha1(etag_source.encode()).hexdigest()[:20] + '"'  # noqa: S324
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)

    changed = base if since_at is None else (*base, File.updated_at >= since_at)
    where = (*changed, File.deleted_at.is_(None)) if since_at is None else changed
    files = list(db.scalars(select(File).where(*where)))
    live = [f for f in files if f.deleted_at is None]
    removed = [str(f.id) for f in files if f.deleted_at is not None]
    paths = _folder_paths(db, current_user) if live else {}
    rows = [
        [
            str(f.id),
            f.name,
            f.mime_type or "",
            f.size,
            _iso(f.taken_at),
            _iso(f.modified_at),
            _iso(f.created_at),
            (f.content_hash or "")[:16],
            f.thumbhash or "",
            paths.get(f.folder_id, "") if f.folder_id else "",
        ]
        for f in live
    ]
    return LibraryIndex(
        cursor=cursor,
        full=since_at is None,
        columns=INDEX_COLUMNS,
        rows=rows,
        removed=removed,
        favorites=favorite_ids,
    )


@router.get("/favorites", response_model=list[FileResponse])
def favorites(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    files = list(
        db.scalars(
            select(File)
            .join(Favorite, Favorite.file_id == File.id)
            .where(
                Favorite.user_id == current_user.id,
                File.owner_id == current_user.id,
                File.deleted_at.is_(None),
            )
            .order_by(Favorite.created_at.desc())
        )
    )
    return decorate(db, current_user, files)


@router.put("/favorites/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_favorite(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        file = file_service.get_file(db, current_user, file_id)
    except file_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if db.get(Favorite, (current_user.id, file.id)) is None:
        db.add(Favorite(user_id=current_user.id, file_id=file.id))
        db.commit()


@router.delete("/favorites/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    favorite = db.get(Favorite, (current_user.id, file_id))
    if favorite is not None:
        db.delete(favorite)
        db.commit()


class Usage(BaseModel):
    used_bytes: int
    quota_bytes: int
    file_count: int


@router.get("/usage", response_model=Usage)
def usage(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.scalar(
        select(func.count())
        .select_from(File)
        .where(File.owner_id == current_user.id, File.deleted_at.is_(None))
    )
    return Usage(
        used_bytes=quota_service.usage_bytes(db, current_user),
        quota_bytes=current_user.storage_quota,
        file_count=count or 0,
    )


class ActivityItem(BaseModel):
    id: uuid.UUID
    action: str
    file_id: uuid.UUID | None
    file_name: str
    detail: str | None
    created_at: datetime


@router.get("/activity", response_model=list[ActivityItem])
def activity(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows: list[Activity] = activity_service.list_recent(db, current_user.id, limit)
    return [
        ActivityItem(
            id=r.id,
            action=r.action,
            file_id=r.file_id,
            file_name=r.file_name,
            detail=r.detail,
            created_at=r.created_at,
        )
        for r in rows
    ]
