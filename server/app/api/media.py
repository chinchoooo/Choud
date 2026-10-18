"""Inline previews and thumbnails for `<img>`, `<video>` and in-app viewers.

Browsers and media players cannot send an Authorization header from a tag, so
these routes take a short-lived, read-only *media token* in the URL path
(`POST /api/media/token` issues one). It is a different token type from the
access token: it opens only these two routes, only for the owner's own files,
and expires after an hour. Everything served here is owner-scoped like any other
file route.

Because user-uploaded bytes are served from the API's own origin, only a small
allowlist of media types is ever sent inline; everything else (HTML, SVG, XML,
scripts...) is sent as an opaque download, with `nosniff` and a locked-down
Content-Security-Policy, so an uploaded page can never run script in the app.
"""

import struct
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse as FastAPIFileResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import rate_limit
from app.core.security import (
    MEDIA_TOKEN_MINUTES,
    MEDIA_TOKEN_TYPE,
    TokenError,
    create_media_token,
    decode_token,
)
from app.models.file import File
from app.models.user import User
from app.services import file_service, media_cache, thumbnail_service

router = APIRouter(prefix="/api/media", tags=["media"])

# Types that are safe to render inline. Anything not listed is a forced download.
INLINE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/bmp",
    "application/pdf",
    "text/plain",
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/ogg",
    "video/x-matroska",
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/flac",
}


class MediaToken(BaseModel):
    token: str
    expires_in: int


@router.post(
    "/token", dependencies=[Depends(rate_limit("media-token", 120, 60))], response_model=MediaToken
)
def issue_token(current_user: User = Depends(get_current_user)) -> MediaToken:
    return MediaToken(
        token=create_media_token(current_user.id), expires_in=MEDIA_TOKEN_MINUTES * 60
    )


def _user_for(db: Session, token: str) -> User:
    unauthorized = HTTPException(status_code=401, detail="invalid or expired media token")
    try:
        payload = decode_token(token, expected_type=MEDIA_TOKEN_TYPE)
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (TokenError, KeyError, ValueError, TypeError) as exc:
        raise unauthorized from exc
    if user is None or not user.is_active:
        raise unauthorized
    return user


def safe_headers(*, pdf: bool = False) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "private, max-age=3600",
    }
    if not pdf:
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return headers


@router.get("/{token}/{file_id}/content")
def content(token: str, file_id: uuid.UUID, db: Session = Depends(get_db)):
    """The file's bytes, with HTTP Range support so video can seek."""
    user = _user_for(db, token)
    try:
        file = file_service.get_file(db, user, file_id)
    except file_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        path = media_cache.cached_path(file)
    except file_service.StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    mime = (file.mime_type or "").split(";")[0].strip().lower()
    inline = mime in INLINE_TYPES
    return FastAPIFileResponse(
        path,
        media_type=mime if inline else "application/octet-stream",
        filename=file.name,
        content_disposition_type="inline" if inline else "attachment",
        headers=safe_headers(pdf=mime == "application/pdf"),
    )


@router.get("/{token}/{file_id}/thumbnail")
def thumbnail(
    token: str,
    file_id: uuid.UUID,
    size: int = Query(default=256),
    db: Session = Depends(get_db),
):
    user = _user_for(db, token)
    try:
        file = file_service.get_file(db, user, file_id)
    except file_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        path = thumbnail_service.get_thumbnail(file, size)
    except thumbnail_service.ThumbnailUnavailable as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except file_service.StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FastAPIFileResponse(path, media_type="image/jpeg", headers=safe_headers())


# --- stable, cacheable thumbnails for the phone app -----------------------------------------------
#
# The token routes above change their URL every hour, so no HTTP cache can ever reuse a thumbnail.
# These take the normal Authorization header instead and have a URL that only changes when the
# picture does (`v` is a prefix of its content hash), so the phone can keep each thumbnail forever.

thumbs_router = APIRouter(prefix="/api/thumbs", tags=["media"])
IMMUTABLE = "private, max-age=31536000, immutable"


@thumbs_router.get("/{file_id}")
def stable_thumbnail(
    file_id: uuid.UUID,
    request: Request,
    size: int = Query(default=256),
    format: str = Query(default="webp"),  # noqa: A002 - the query parameter is called "format"
    v: str | None = Query(default=None, max_length=64),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        file = file_service.get_file(db, user, file_id)
    except file_service.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    etag = f'"{(file.content_hash or "")[:24]}-{size}-{format}"'
    headers = {"ETag": etag, "Cache-Control": IMMUTABLE, "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    try:
        path = thumbnail_service.get_thumbnail(file, size, format)
    except thumbnail_service.ThumbnailUnavailable as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except file_service.StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FastAPIFileResponse(path, media_type=thumbnail_service.FORMATS[format], headers=headers)


MAX_BATCH = 48
MAX_BATCH_GENERATE = 4  # thumbnails made on the spot per batch; the rest are "pending"

FRAME_OK, FRAME_PENDING, FRAME_NONE = 0, 1, 2


class ThumbBatch(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BATCH)
    size: int = 256
    format: str = "webp"


def _frame(file_id: uuid.UUID, status: int, payload: bytes = b"") -> bytes:
    return file_id.bytes + struct.pack(">BI", status, len(payload)) + payload


@router.post("/thumbs", dependencies=[Depends(rate_limit("thumbs-batch", 240, 60))])
def thumbnail_batch(
    body: ThumbBatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Up to 48 thumbnails in one response: one round trip instead of 48.

    The body is a run of frames, each `[16-byte file id][1 byte status][4 byte big-endian length]
    [bytes]`. Status 0 = the thumbnail, 1 = pending (ask for it on its own), 2 = no thumbnail for
    this id (unknown, not yours, or not an image/video). Only thumbnails that already exist are
    sent inline, plus at most a few made on the spot, so one slow photo cannot hold up the rest.
    """
    if (
        body.size not in thumbnail_service.ALLOWED_SIZES
        or body.format not in thumbnail_service.FORMATS
    ):
        raise HTTPException(status_code=422, detail="unsupported size or format")
    rows = db.execute(
        select(File).where(
            File.id.in_(body.ids), File.owner_id == user.id, File.deleted_at.is_(None)
        )
    ).scalars()
    files = {file.id: file for file in rows}
    directory = thumbnail_service.thumbs_dir()
    budget = MAX_BATCH_GENERATE

    def frames():
        nonlocal budget
        for file_id in body.ids:
            file = files.get(file_id)
            if file is None or thumbnail_service.kind_of(file) is None or not file.content_hash:
                yield _frame(file_id, FRAME_NONE)
                continue
            cached = directory / f"{file.content_hash}-{body.size}.{body.format}"
            if not cached.exists():
                if budget <= 0:
                    yield _frame(file_id, FRAME_PENDING)
                    continue
                budget -= 1
                try:
                    cached = thumbnail_service.get_thumbnail(file, body.size, body.format)
                except (thumbnail_service.ThumbnailUnavailable, file_service.StorageError):
                    yield _frame(file_id, FRAME_NONE)
                    continue
            try:
                yield _frame(file_id, FRAME_OK, cached.read_bytes())
            except OSError:
                yield _frame(file_id, FRAME_PENDING)

    return StreamingResponse(
        frames(),
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
