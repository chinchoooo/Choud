"""/api/instance: what this server is and whether its share links work from outside.

Clients (the phone app, the web app) read this to say the truth about a link before it is sent:
"anyone can open it", "paused" or "only people on your network can open it".
"""

import json
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services import instance_service, invite_service

router = APIRouter(tags=["instance"])


class InstanceResponse(BaseModel):
    version: str
    public_base_url: str | None
    public_status: str  # ready | paused | not_configured
    public_door_mode: str
    is_admin: bool


class PublicLinksUpdate(BaseModel):
    enabled: bool


class PublicCheck(BaseModel):
    ok: bool
    detail: str
    door: str | None = None
    client_ip: str | None = None


def _require_admin(db: Session, user: User) -> None:
    if not invite_service.is_admin(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the administrator can do this")


def _describe(db: Session, user: User) -> InstanceResponse:
    settings = get_settings()
    return InstanceResponse(
        version=__version__,
        public_base_url=instance_service.public_base_url() or None,
        public_status=instance_service.public_status(db),
        public_door_mode=settings.public_door_mode,
        is_admin=invite_service.is_admin(db, user),
    )


@router.get("/api/instance", response_model=InstanceResponse)
def instance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _describe(db, user)


@router.put("/api/admin/public-links", response_model=InstanceResponse)
def set_public_links(
    body: PublicLinksUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The kill switch: while off, the public door answers 404 for every share link."""
    _require_admin(db, user)
    instance_service.set_value(db, instance_service.PUBLIC_LINKS, "1" if body.enabled else "0")
    return _describe(db, user)


@router.post("/api/admin/public-links/check", response_model=PublicCheck)
def check_public_links(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Asks this server's own public address for `/s/_health`, the way a stranger would."""
    _require_admin(db, user)
    base = instance_service.public_base_url()
    if not base:
        return PublicCheck(ok=False, detail="PUBLIC_BASE_URL is not set.")
    try:
        with urllib.request.urlopen(f"{base}/s/_health", timeout=8) as reply:  # noqa: S310
            data = json.loads(reply.read(4096) or b"{}")
    except urllib.error.HTTPError as exc:
        return PublicCheck(ok=False, detail=f"The public address answered {exc.code}.")
    except Exception as exc:
        return PublicCheck(ok=False, detail=f"Could not reach {base}: {exc.__class__.__name__}.")
    if not data.get("ok"):
        return PublicCheck(ok=False, detail="The public address answered, but not as Choud.")
    return PublicCheck(
        ok=True,
        detail="Share links work from outside your network.",
        door=data.get("door"),
        client_ip=data.get("client_ip"),
    )
