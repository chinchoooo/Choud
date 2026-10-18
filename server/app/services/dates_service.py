"""Repair the dates of photos and videos that were uploaded without one.

Files that arrive without a "taken" date show up on the upload day, scrambling a photo timeline.
This finds the real date from what the file itself tells us, in order of trust:

  1. its name (IMG_20250206_160717396.jpg, PXL_..., VID_..., Screenshot_..., WhatsApp, Signal),
  2. the photo's own EXIF "date taken" (read in place from the stored object; images only).

Only files with no taken date are touched, nothing else about a file changes, and every change is
reported so a preview (`dry_run`) shows exactly what would happen.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.user import User
from app.services.storage_service import get_storage_service

MAX_EXIF_BYTES = 80 * 1024 * 1024

_NAME_PATTERNS = [
    # IMG_20250206_160717396.jpg, PXL_20250206_160717396, VID_20250206_160717, MVIMG_..., BURST...
    re.compile(
        r"(?:IMG|VID|PXL|PANO|MVIMG|BURST|MOV|DSC)[-_]?(\d{4})(\d{2})(\d{2})[-_]?(\d{2})(\d{2})(\d{2})"
    ),
    re.compile(
        r"Screenshot[-_ ](\d{4})[-_]?(\d{2})[-_]?(\d{2})[-_ T](\d{2})[-_.]?(\d{2})[-_.]?(\d{2})"
    ),
    re.compile(r"signal-(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})"),
    re.compile(
        r"(\d{4})-(\d{2})-(\d{2})[ _T](\d{2})[.:\-](\d{2})[.:\-](\d{2})"
    ),  # 2025-02-06 16.07.17
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[-_](\d{2})(\d{2})(\d{2})(?!\d)"),  # 20250206_160717
    # Date only (WhatsApp: IMG-20250206-WA0001.jpg)
    re.compile(r"(?:IMG|VID)-(\d{4})(\d{2})(\d{2})-WA\d+"),
]


def _build(parts: tuple[str, ...], now: datetime) -> datetime | None:
    numbers = [int(p) for p in parts]
    while len(numbers) < 6:
        numbers.append(0)
    year, month, day, hour, minute, second = numbers[:6]
    try:
        value = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        return None
    if value.year < 1990 or value > now.replace(year=now.year + 1):
        return None
    return value


def date_from_name(name: str, now: datetime | None = None) -> datetime | None:
    """The date a file name claims, or None. Times in names are the phone's local time."""
    now = now or datetime.now(UTC)
    for pattern in _NAME_PATTERNS:
        match = pattern.search(name)
        if match:
            value = _build(match.groups(), now)
            if value is not None:
                return value
    return None


def date_from_exif(path: Path, now: datetime | None = None) -> datetime | None:
    """The EXIF "date taken" of a photo, or None (no EXIF, not an image, unreadable)."""
    now = now or datetime.now(UTC)
    try:
        from PIL import Image

        if path.stat().st_size > MAX_EXIF_BYTES:
            return None
        with Image.open(path) as image:
            exif = image.getexif()
            raw = None
            try:
                raw = exif.get_ifd(0x8769).get(36867) or exif.get_ifd(0x8769).get(
                    36868
                )  # taken / digitized
            except Exception:
                raw = None
            raw = raw or exif.get(306)  # DateTime (last modified), the weakest fallback
    except Exception:
        return None
    if not isinstance(raw, str):
        return None
    match = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", raw.strip())
    return _build(match.groups(), now) if match else None


@dataclass
class DateFixReport:
    checked: int = 0
    from_name: int = 0
    from_exif: int = 0
    no_date_found: int = 0
    examples: list[str] = None  # a few "name -> date" lines

    def __post_init__(self) -> None:
        if self.examples is None:
            self.examples = []

    @property
    def fixed(self) -> int:
        return self.from_name + self.from_exif


def fix_dates(db: Session, user: User, *, dry_run: bool = True) -> DateFixReport:
    """Give every photo/video without a taken date the best date we can find."""
    report = DateFixReport()
    storage = get_storage_service()
    files = db.execute(
        select(File).where(
            File.owner_id == user.id,
            File.deleted_at.is_(None),
            File.taken_at.is_(None),
            or_(File.mime_type.like("image/%"), File.mime_type.like("video/%")),
        )
    ).scalars()
    for file in files:
        report.checked += 1
        found = date_from_name(file.name)
        source = "name"
        if found is None and (file.mime_type or "").startswith("image/") and file.content_hash:
            local = storage.local_path(file.content_hash)
            if local is not None:
                found = date_from_exif(local)
                source = "exif"
        if found is None:
            report.no_date_found += 1
            continue
        if source == "name":
            report.from_name += 1
        else:
            report.from_exif += 1
        if len(report.examples) < 8:
            report.examples.append(f"{file.name} -> {found.date().isoformat()} ({source})")
        if not dry_run:
            file.taken_at = found
            if file.modified_at is None:
                file.modified_at = found
    if not dry_run:
        db.commit()
    return report
