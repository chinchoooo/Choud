"""Public share links: what a visitor sees at `/s/<token>` (Phase 12).

No account is needed, so nothing here trusts anything but the token. Unknown, expired, revoked and
deleted-target links all answer with the same 404 page. A password-protected link shows a form;
a correct password sets a short-lived signed cookie scoped to that one link.
"""

import uuid

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import FileResponse as FastAPIFileResponse
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.media import INLINE_TYPES, safe_headers
from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.models.share import Share
from app.services import file_service, media_cache, share_pages, share_service, thumbnail_service

router = APIRouter(prefix="/s", tags=["public-shares"])

_view_limit = Depends(rate_limit("share-view", 300, 60))
_unlock_limit = Depends(rate_limit("share-unlock", 10, 60))


def _cookie_name(share: Share) -> str:
    return f"cs_{share.id.hex[:12]}"


def _html(markup: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(markup, status_code=status_code, headers=share_pages.PAGE_HEADERS)


def _not_found() -> HTMLResponse:
    return _html(share_pages.not_found(), 404)


def _gate(request: Request, db: Session, token: str) -> tuple[Share | None, HTMLResponse | None]:
    """The share if the visitor may see it; otherwise the page to show instead."""
    share = share_service.find_active(db, token)
    if share is None:
        return None, _not_found()
    if not share_service.is_unlocked(share, request.cookies.get(_cookie_name(share))):
        return None, _html(share_pages.unlock_form(token), 401)
    return share, None


@router.get("/{token}", response_class=HTMLResponse, dependencies=[_view_limit])
def view(
    token: str,
    request: Request,
    folder: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    share, blocked = _gate(request, db, token)
    if blocked is not None:
        return blocked
    share_service.record_access(db, share, download=False)

    if share.file_id is not None:
        file = file_service.get_file(db, _owner(db, share), share.file_id)
        return _html(share_pages.file_page(token, file, _inline_ok(file)))

    target = share_service.folder_in_share(db, share, folder)
    if target is None:
        return _not_found()
    folders, files = share_service.folder_contents(db, share, target)
    trail = share_service.breadcrumb(db, share, target)
    return _html(
        share_pages.folder_page(token, target.name, trail, folders, files, share.folder_id)
    )


@router.post("/{token}/unlock", dependencies=[_unlock_limit])
def unlock(
    token: str,
    request: Request,
    password: str = Form(default="", max_length=256),
    db: Session = Depends(get_db),
):
    share = share_service.find_active(db, token)
    if share is None:
        return _not_found()
    if share.password_hash is None:
        return RedirectResponse(f"/s/{token}", status_code=303)
    if not share_service.check_password(share, password):
        return _html(share_pages.unlock_form(token, error=True), 401)
    response = RedirectResponse(f"/s/{token}", status_code=303)
    response.set_cookie(
        _cookie_name(share),
        share_service.make_unlock_value(share),
        max_age=share_service.UNLOCK_SECONDS,
        path=f"/s/{token}",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    for name, value in share_pages.PAGE_HEADERS.items():
        response.headers[name] = value
    return response


@router.get("/{token}/file/{file_id}/open", response_class=HTMLResponse, dependencies=[_view_limit])
def open_file(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """A preview page for one file inside a shared folder."""
    share, blocked = _gate(request, db, token)
    if blocked is not None:
        return blocked
    file = share_service.file_in_share(db, share, file_id)
    if file is None:
        return _not_found()
    share_service.record_access(db, share, download=False)
    return _html(share_pages.file_page(token, file, _inline_ok(file)))


@router.get("/{token}/file/{file_id}", dependencies=[_view_limit])
def download(
    token: str,
    file_id: uuid.UUID,
    request: Request,
    inline: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    share, blocked = _gate(request, db, token)
    if blocked is not None:
        return blocked
    file = share_service.file_in_share(db, share, file_id)
    if file is None:
        return _not_found()
    try:
        path = media_cache.cached_path(file)
    except file_service.StorageError:
        return Response("The file could not be read.", status_code=500)

    mime = (file.mime_type or "").split(";")[0].strip().lower()
    show_inline = inline and mime in INLINE_TYPES  # only types that are safe to render
    share_service.record_access(db, share, download=not show_inline)
    return FastAPIFileResponse(
        path,
        media_type=mime if show_inline else "application/octet-stream",
        filename=file.name,
        content_disposition_type="inline" if show_inline else "attachment",
        headers=safe_headers(pdf=show_inline and mime == "application/pdf"),
    )


@router.get("/{token}/file/{file_id}/thumbnail", dependencies=[_view_limit])
def thumbnail(token: str, file_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    share, blocked = _gate(request, db, token)
    if blocked is not None:
        return blocked
    file = share_service.file_in_share(db, share, file_id)
    if file is None:
        return _not_found()
    try:
        path = thumbnail_service.get_thumbnail(file, 128)
    except thumbnail_service.ThumbnailUnavailable:
        return Response(status_code=415)
    except file_service.StorageError:
        return Response(status_code=500)
    return FastAPIFileResponse(path, media_type="image/jpeg", headers=safe_headers())


def _inline_ok(file) -> bool:
    return (file.mime_type or "").split(";")[0].strip().lower() in INLINE_TYPES


def _owner(db: Session, share: Share):
    """The share owner, to reuse the owner-scoped file lookups (the visitor is anonymous)."""
    from app.models.user import User

    return db.get(User, share.owner_id)
