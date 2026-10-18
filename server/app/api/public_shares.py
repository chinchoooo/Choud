"""Public share links: what a visitor sees at `/s/<token>` (Phase 12).

No account is needed, so nothing here trusts anything but the token. Unknown, expired, revoked and
deleted-target links all answer with the same 404 page. A password-protected link shows a form;
a correct password sets a short-lived signed cookie scoped to that one link.
"""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi import File as FastAPIFile
from fastapi.responses import FileResponse as FastAPIFileResponse
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from app.api.media import INLINE_TYPES, safe_headers
from app.core.database import get_db
from app.core.rate_limit import client_ip, rate_limit
from app.models.share import Share
from app.models.user import User
from app.schemas.files import FileUpdate
from app.services import (
    file_service,
    instance_service,
    media_cache,
    share_pages,
    share_service,
    thumbnail_service,
)
from app.services.errors import PayloadTooLargeError, QuotaError


def public_door_guard(request: Request, db: Session = Depends(get_db)) -> None:
    """The kill switch.

    The proxy marks requests that came through the PUBLIC door. While an administrator has paused
    public links those get a plain 404; the private door is unaffected."""
    if request.headers.get(
        "x-choud-door"
    ) == "public" and not instance_service.public_links_enabled(db):
        raise HTTPException(status_code=404, detail="Not found")


router = APIRouter(prefix="/s", tags=["public-shares"], dependencies=[Depends(public_door_guard)])

_view_limit = Depends(rate_limit("share-view", 300, 60))
_unlock_limit = Depends(rate_limit("share-unlock", 10, 60))


def _cookie_name(share: Share) -> str:
    return f"cs_{share.id.hex[:12]}"


def _html(markup: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(markup, status_code=status_code, headers=share_pages.PAGE_HEADERS)


def _not_found() -> HTMLResponse:
    return _html(share_pages.not_found(), 404)


def _reader_gate(
    request: Request, db: Session, token: str
) -> tuple[Share | None, HTMLResponse | None]:
    """Like `_gate`, but a file-request (drop) link can never be read from."""
    share, blocked = _gate(request, db, token)
    if blocked is None and share_service.is_drop(share):
        return None, _not_found()
    return share, blocked


def _gate(request: Request, db: Session, token: str) -> tuple[Share | None, HTMLResponse | None]:
    """The share if the visitor may see it; otherwise the page to show instead."""
    share = share_service.find_active(db, token)
    if share is None:
        return None, _not_found()
    if not share_service.is_unlocked(share, request.cookies.get(_cookie_name(share))):
        return None, _html(share_pages.unlock_form(token), 401)
    return share, None


@router.get("/_health", dependencies=[_view_limit])
def health(request: Request) -> dict:
    """Answers "is this the public door, and who does the server think you are?". Used by the setup
    script and the admin check to prove a link works from outside."""
    return {
        "ok": True,
        "door": "public" if request.headers.get("x-choud-door") == "public" else "private",
        "client_ip": client_ip(request),
    }


@router.get("/{token}", response_class=HTMLResponse, dependencies=[_view_limit])
def view(
    token: str,
    request: Request,
    folder: uuid.UUID | None = Query(default=None),
    sent: int = Query(default=0, ge=0, le=100),
    db: Session = Depends(get_db),
):
    share, blocked = _gate(request, db, token)
    if blocked is not None:
        return blocked
    share_service.record_access(db, share, download=False)

    if share_service.is_drop(share):
        root = share_service.folder_in_share(db, share, None)
        if root is None:
            return _not_found()
        return _html(share_pages.drop_page(token, root.name, sent=sent))

    if share.file_id is not None:
        file = file_service.get_file(db, _owner(db, share), share.file_id)
        return _html(
            share_pages.file_page(
                token, file, _inline_ok(file), editable=share_service.is_editable(share)
            )
        )

    target = share_service.folder_in_share(db, share, folder)
    if target is None:
        return _not_found()
    folders, files = share_service.folder_contents(db, share, target)
    trail = share_service.breadcrumb(db, share, target)
    return _html(
        share_pages.folder_page(
            token,
            target.name,
            trail,
            folders,
            files,
            share.folder_id,
            current=target,
            editable=share_service.is_editable(share),
        )
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
    share, blocked = _reader_gate(request, db, token)
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
    share, blocked = _reader_gate(request, db, token)
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
    share, blocked = _reader_gate(request, db, token)
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
    return db.get(User, share.owner_id)


# --- edit links ----------------------------------------------------------------------------------
#
# A link made with permission "edit" lets visitors add files, make folders, rename and delete
# inside the shared folder (or upload a new version of a single shared file). Every action
# re-checks that the target lies inside the link; deletes go to the OWNER'S TRASH (never a hard
# delete) and same-name uploads become new VERSIONS, so nothing an editor does is unrecoverable.
# Uploads count against the owner's quota and obey the normal size limits.

_edit_limit = Depends(rate_limit("share-edit", 60, 60))
MAX_FILES_PER_UPLOAD = 20


def _back(share: Share, folder_id: uuid.UUID | None) -> str:
    if share.folder_id is None or folder_id is None or folder_id == share.folder_id:
        return ""
    return f"?folder={folder_id}"


def _refused(token: str, message: str, status_code: int, back: str = "") -> HTMLResponse:
    return _html(share_pages.message_page(token, message, back), status_code)


def _uploader(
    request: Request, db: Session, token: str
) -> tuple[Share | None, HTMLResponse | None]:
    """The share if the visitor may add files: an edit link or a file-request (drop) link."""
    share, blocked = _gate(request, db, token)
    if blocked is not None:
        return None, blocked
    if not (share_service.is_editable(share) or share_service.is_drop(share)):
        return None, _refused(token, "This link is view-only.", 403)
    return share, None


def _editor(request: Request, db: Session, token: str) -> tuple[Share | None, HTMLResponse | None]:
    """The share if the visitor is allowed in AND the link is an edit link."""
    share, blocked = _gate(request, db, token)
    if blocked is not None:
        return None, blocked
    if not share_service.is_editable(share):
        return None, _refused(token, "This link is view-only.", 403)
    return share, None


def _folder_id(raw: str) -> tuple[uuid.UUID | None, bool]:
    """(parsed id, ok). An empty value means "the shared folder itself"."""
    if not raw:
        return None, True
    try:
        return uuid.UUID(raw), True
    except ValueError:
        return None, False


def _clean_name(raw: str) -> str:
    """Names are validated exactly like everywhere else (no slashes, no traversal, not blank)."""
    return FileUpdate(name=raw).name


@router.post("/{token}/upload", dependencies=[_edit_limit])
async def upload(
    token: str,
    request: Request,
    folder: str = Form(default="", max_length=64),
    files: list[UploadFile] = FastAPIFile(...),
    db: Session = Depends(get_db),
):
    share, blocked = _uploader(request, db, token)
    if blocked is not None:
        return blocked
    owner = _owner(db, share)
    if len(files) > MAX_FILES_PER_UPLOAD:
        return _refused(token, f"Add at most {MAX_FILES_PER_UPLOAD} files at a time.", 422)

    if share_service.is_drop(share):
        return await _drop_upload(db, share, owner, token, files)

    if share.file_id is not None:
        # A file link: the only edit is a new version of that one file, under its own name.
        if len(files) != 1:
            return _refused(token, "Choose exactly one file.", 422)
        current = file_service.get_file(db, owner, share.file_id)
        parent_id, forced_name, back = current.folder_id, current.name, ""
    else:
        wanted, ok = _folder_id(folder)
        target = share_service.folder_in_share(db, share, wanted) if ok else None
        if target is None:
            return _not_found()
        parent_id, forced_name, back = target.id, None, _back(share, target.id)

    try:
        for upload_file in files:
            await file_service.upload_file(db, owner, upload_file, parent_id, forced_name)
    except file_service.ValidationError as exc:
        return _refused(token, str(exc), 422, back)
    except file_service.ConflictError as exc:
        return _refused(token, str(exc), 409, back)
    except (PayloadTooLargeError, QuotaError) as exc:
        return _refused(token, str(exc), 413, back)
    except file_service.StorageError:
        return _refused(token, "The file could not be stored. Try again.", 502, back)
    share_service.record_access(db, share, download=False)
    return RedirectResponse(f"/s/{token}{back}", status_code=303)


async def _drop_upload(db: Session, share: Share, owner: User, token: str, files: list[UploadFile]):
    """A file request: files go into the shared folder, never over anything already there."""
    root = share_service.folder_in_share(db, share, None)
    if root is None:
        return _not_found()
    sent = 0
    try:
        for upload_file in files:
            name = share_service.free_name(
                db, owner, root.id, file_service._validate_filename(upload_file.filename)
            )
            await file_service.upload_file(db, owner, upload_file, root.id, name, expect_new=True)
            sent += 1
    except file_service.ValidationError as exc:
        return _refused(token, str(exc), 422)
    except file_service.ConflictError as exc:
        return _refused(token, str(exc), 409)
    except (PayloadTooLargeError, QuotaError) as exc:
        return _refused(token, str(exc), 413)
    except file_service.StorageError:
        return _refused(token, "The file could not be stored. Try again.", 502)
    except ValueError as exc:
        return _refused(token, str(exc), 409)
    share_service.record_access(db, share, download=False)
    return RedirectResponse(f"/s/{token}?sent={sent}", status_code=303)


@router.post("/{token}/mkdir", dependencies=[_edit_limit])
def make_folder(
    token: str,
    request: Request,
    parent: str = Form(default="", max_length=64),
    name: str = Form(max_length=255),
    db: Session = Depends(get_db),
):
    share, blocked = _editor(request, db, token)
    if blocked is not None:
        return blocked
    if share.folder_id is None:
        return _refused(token, "Folders can only be made on a folder link.", 403)
    wanted, ok = _folder_id(parent)
    target = share_service.folder_in_share(db, share, wanted) if ok else None
    if target is None:
        return _not_found()
    back = _back(share, target.id)
    try:
        file_service.create_folder(db, _owner(db, share), _clean_name(name), target.id)
    except PydanticValidationError:
        return _refused(token, "That is not a valid folder name.", 422, back)
    except file_service.ConflictError as exc:
        return _refused(token, str(exc), 409, back)
    return RedirectResponse(f"/s/{token}{back}", status_code=303)


@router.post("/{token}/rename", dependencies=[_edit_limit])
def rename_file(
    token: str,
    request: Request,
    file_id: uuid.UUID = Form(),
    name: str = Form(max_length=255),
    db: Session = Depends(get_db),
):
    share, blocked = _editor(request, db, token)
    if blocked is not None:
        return blocked
    if share.folder_id is None:
        return _refused(token, "A single-file link cannot rename the file.", 403)
    file = share_service.file_in_share(db, share, file_id)
    if file is None:
        return _not_found()
    back = _back(share, file.folder_id)
    try:
        file_service.update_file(db, _owner(db, share), file.id, {"name": _clean_name(name)})
    except PydanticValidationError:
        return _refused(token, "That is not a valid file name.", 422, back)
    except file_service.ConflictError as exc:
        return _refused(token, str(exc), 409, back)
    return RedirectResponse(f"/s/{token}{back}", status_code=303)


@router.post("/{token}/trash", dependencies=[_edit_limit])
def trash_file(
    token: str,
    request: Request,
    file_id: uuid.UUID = Form(),
    db: Session = Depends(get_db),
):
    """Delete = move to the owner's trash, where they can restore it."""
    share, blocked = _editor(request, db, token)
    if blocked is not None:
        return blocked
    if share.folder_id is None:
        return _refused(token, "A single-file link cannot delete the file.", 403)
    file = share_service.file_in_share(db, share, file_id)
    if file is None:
        return _not_found()
    back = _back(share, file.folder_id)
    file_service.delete_file(db, _owner(db, share), file.id)
    return RedirectResponse(f"/s/{token}{back}", status_code=303)
