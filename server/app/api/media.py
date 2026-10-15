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

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse as FastAPIFileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import (
    MEDIA_TOKEN_MINUTES,
    MEDIA_TOKEN_TYPE,
    TokenError,
    create_media_token,
    decode_token,
)
from app.models.user import User
from app.services import file_service, media_cache, thumbnail_service

router = APIRouter(prefix="/api/media", tags=["media"])

# Types that are safe to render inline. Anything not listed is a forced download.
_INLINE_EXACT = {
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


@router.post("/token", response_model=MediaToken)
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


def _safe_headers(*, pdf: bool = False) -> dict[str, str]:
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
    inline = mime in _INLINE_EXACT
    return FastAPIFileResponse(
        path,
        media_type=mime if inline else "application/octet-stream",
        filename=file.name,
        content_disposition_type="inline" if inline else "attachment",
        headers=_safe_headers(pdf=mime == "application/pdf"),
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
    return FastAPIFileResponse(path, media_type="image/jpeg", headers=_safe_headers())
