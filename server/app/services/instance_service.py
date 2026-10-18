"""Server-wide switches and the answer to "can people outside my network open my share links?"."""

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.instance_setting import InstanceSetting

PUBLIC_LINKS = "public_links_enabled"


def get_value(db: Session, key: str, default: str = "") -> str:
    row = db.get(InstanceSetting, key)
    return row.value if row is not None else default


def set_value(db: Session, key: str, value: str) -> None:
    row = db.get(InstanceSetting, key)
    if row is None:
        db.add(InstanceSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def public_links_enabled(db: Session) -> bool:
    """On unless an administrator paused it."""
    return get_value(db, PUBLIC_LINKS, "1") != "0"


def public_base_url() -> str:
    return get_settings().public_base_url.strip().rstrip("/")


def public_status(db: Session) -> str:
    """`ready` (works from anywhere), `paused` (switched off) or `not_configured` (no address)."""
    if not public_base_url():
        return "not_configured"
    return "ready" if public_links_enabled(db) else "paused"
