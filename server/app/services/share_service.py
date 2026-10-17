"""Public share links (Phase 12): create, manage, and resolve them.

Rules that keep a link from becoming a hole:

- A link only ever opens what it was made for. A file link opens that one file; a folder link opens
  files and folders *inside that folder* and nothing else (checked by walking up from the item).
- Expired, revoked or deleted-target links all behave like a link that never existed.
- Only the owner can create, list, change or revoke a link, and only for their own files/folders.
- A password is hashed with Argon2id like account passwords; checking it is rate limited at the
  route.
"""

import hashlib
import hmac
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.file import File
from app.models.folder import Folder
from app.models.share import Share
from app.models.user import User
from app.services import activity_service, file_service
from app.services.errors import NotFoundError

UNLOCK_SECONDS = 3600
_MAX_DEPTH = 64  # a folder tree is never this deep; this only stops a cycle from looping forever


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes; they were stored as UTC.
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def is_active(share: Share, now: datetime | None = None) -> bool:
    now = now or _now()
    if share.revoked_at is not None:
        return False
    expires = _aware(share.expires_at)
    return expires is None or expires > now


# --- owner side ------------------------------------------------------------------------------


def create_share(
    db: Session,
    owner: User,
    *,
    file_id: uuid.UUID | None,
    folder_id: uuid.UUID | None,
    expires_in_hours: int | None,
    password: str | None,
    label: str | None,
    permission: str = "view",
) -> Share:
    if (file_id is None) == (folder_id is None):
        raise ValueError("give exactly one of file_id or folder_id")
    # Ownership and "not in the trash" are enforced by the same lookups every other route uses.
    if file_id is not None:
        file_service.get_file(db, owner, file_id)
    else:
        file_service.get_folder(db, owner, folder_id)

    share = Share(
        id=uuid.uuid4(),
        owner_id=owner.id,
        file_id=file_id,
        folder_id=folder_id,
        token=secrets.token_urlsafe(32),
        label=label,
        permission=permission,
        password_hash=hash_password(password) if password else None,
        expires_at=_now() + timedelta(hours=expires_in_hours) if expires_in_hours else None,
        download_count=0,
    )
    db.add(share)
    name = _target_name(db, share) or "shared item"
    activity_service.record(
        db,
        owner.id,
        "shared",
        file_id=file_id,
        file_name=name,
        detail="public link (can edit)" if permission == "edit" else "public link",
    )
    db.commit()
    db.refresh(share)
    return share


def list_shares(db: Session, owner: User) -> list[Share]:
    stmt = (
        select(Share)
        .where(Share.owner_id == owner.id, Share.revoked_at.is_(None))
        .order_by(Share.created_at.desc())
    )
    return list(db.scalars(stmt))


def _get_owned(db: Session, owner: User, share_id: uuid.UUID) -> Share:
    share = db.get(Share, share_id)
    if share is None or share.owner_id != owner.id or share.revoked_at is not None:
        raise NotFoundError("share not found")
    return share


def revoke_share(db: Session, owner: User, share_id: uuid.UUID) -> None:
    share = _get_owned(db, owner, share_id)
    share.revoked_at = _now()
    db.commit()


def update_share(db: Session, owner: User, share_id: uuid.UUID, data: dict) -> Share:
    share = _get_owned(db, owner, share_id)
    if "label" in data:
        share.label = data["label"]
    if data.get("permission"):
        share.permission = data["permission"]
    if "password" in data:
        share.password_hash = hash_password(data["password"]) if data["password"] else None
    if "expires_in_hours" in data:
        hours = data["expires_in_hours"]
        share.expires_at = _now() + timedelta(hours=hours) if hours else None
    db.commit()
    db.refresh(share)
    return share


def _target_name(db: Session, share: Share) -> str | None:
    if share.file_id is not None:
        file = db.get(File, share.file_id)
        return file.name if file else None
    folder = db.get(Folder, share.folder_id)
    return folder.name if folder else None


def describe(db: Session, share: Share) -> dict:
    """The fields the API shows for a share (never the password hash)."""
    return {
        "id": share.id,
        "kind": "file" if share.file_id is not None else "folder",
        "target_id": share.file_id or share.folder_id,
        "target_name": _target_name(db, share) or "(deleted)",
        "token": share.token,
        "url_path": f"/s/{share.token}",
        "label": share.label,
        "has_password": share.password_hash is not None,
        "permission": share.permission,
        "expires_at": share.expires_at,
        "created_at": share.created_at,
        "download_count": share.download_count,
        "last_accessed_at": share.last_accessed_at,
        "active": is_active(share),
    }


def is_editable(share: Share) -> bool:
    return share.permission == "edit"


# --- visitor side ---------------------------------------------------------------------------


def find_active(db: Session, token: str) -> Share | None:
    """The share for `token` if it is usable right now, else None (never says why)."""
    if not token or len(token) > 64:
        return None
    share = db.scalar(select(Share).where(Share.token == token))
    if share is None or not is_active(share):
        return None
    # The target must still exist and not be in the trash.
    if share.file_id is not None:
        file = db.get(File, share.file_id)
        if file is None or file.deleted_at is not None or file.owner_id != share.owner_id:
            return None
    else:
        folder = db.get(Folder, share.folder_id)
        if folder is None or folder.owner_id != share.owner_id:
            return None
    return share


def check_password(share: Share, password: str) -> bool:
    return share.password_hash is not None and verify_password(password, share.password_hash)


def _unlock_signature(share: Share, expires: int) -> str:
    secret = get_settings().jwt_secret.encode()
    # Changing the password changes the fingerprint, which invalidates every old unlock.
    fingerprint = hashlib.sha256((share.password_hash or "").encode()).hexdigest()[:16]
    message = f"{share.id}:{expires}:{fingerprint}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def make_unlock_value(share: Share, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + UNLOCK_SECONDS)
    return f"{expires}.{_unlock_signature(share, expires)}"


def is_unlocked(share: Share, cookie_value: str | None, now: float | None = None) -> bool:
    """Open to everyone when there is no password; otherwise needs a valid unlock cookie."""
    if share.password_hash is None:
        return True
    if not cookie_value or "." not in cookie_value:
        return False
    expires_text, _, signature = cookie_value.partition(".")
    try:
        expires = int(expires_text)
    except ValueError:
        return False
    if expires < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(signature, _unlock_signature(share, expires))


def _is_inside(db: Session, folder_id: uuid.UUID | None, root_id: uuid.UUID) -> bool:
    """Is `folder_id` the shared folder `root_id`, or somewhere below it?"""
    current = folder_id
    for _ in range(_MAX_DEPTH):
        if current is None:
            return False
        if current == root_id:
            return True
        folder = db.get(Folder, current)
        if folder is None:
            return False
        current = folder.parent_id
    return False


def folder_in_share(db: Session, share: Share, folder_id: uuid.UUID | None) -> Folder | None:
    """The folder to show: the shared one by default, or one inside it. Never anything else."""
    if share.folder_id is None:
        return None
    target = folder_id or share.folder_id
    folder = db.get(Folder, target)
    if folder is None or folder.owner_id != share.owner_id:
        return None
    return folder if _is_inside(db, target, share.folder_id) else None


def file_in_share(db: Session, share: Share, file_id: uuid.UUID) -> File | None:
    """The file if this link covers it (the shared file, or one inside the shared folder)."""
    file = db.get(File, file_id)
    if file is None or file.deleted_at is not None or file.owner_id != share.owner_id:
        return None
    if share.file_id is not None:
        return file if file.id == share.file_id else None
    return file if _is_inside(db, file.folder_id, share.folder_id) else None


def folder_contents(db: Session, share: Share, folder: Folder) -> tuple[list[Folder], list[File]]:
    folders = list(
        db.scalars(
            select(Folder)
            .where(Folder.owner_id == share.owner_id, Folder.parent_id == folder.id)
            .order_by(Folder.name)
        )
    )
    files = list(
        db.scalars(
            select(File)
            .where(
                File.owner_id == share.owner_id,
                File.folder_id == folder.id,
                File.deleted_at.is_(None),
            )
            .order_by(File.name)
        )
    )
    return folders, files


def breadcrumb(db: Session, share: Share, folder: Folder) -> list[Folder]:
    """The path from the shared folder down to `folder` (inclusive), for navigation."""
    chain: list[Folder] = []
    current: Folder | None = folder
    for _ in range(_MAX_DEPTH):
        if current is None:
            break
        chain.append(current)
        if current.id == share.folder_id:
            break
        current = db.get(Folder, current.parent_id) if current.parent_id else None
    return list(reversed(chain))


def record_access(db: Session, share: Share, *, download: bool) -> None:
    share.last_accessed_at = _now()
    if download:
        share.download_count = (share.download_count or 0) + 1
    db.commit()
