"""Search inside files (Phase 14): index their text in the background, then query it.

Indexing is derived data and never blocks an upload. A background loop finds live files whose
current content has no up-to-date `file_text` row and extracts their text a few at a time. Types
that are not text (photos, videos, archives...) get a cheap "skipped" row so they are not looked at
again. Searching uses PostgreSQL full-text search (whole-word matching, ranked); the SQLite used by
the tests falls back to a plain case-insensitive substring match.
"""

import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_text import FileText
from app.models.user import User
from app.services import file_service, text_extract

logger = logging.getLogger(__name__)

SNIPPET_CONTEXT = 90


def _pending_query(limit: int):
    return (
        select(File)
        .outerjoin(FileText, FileText.file_id == File.id)
        .where(
            File.deleted_at.is_(None),
            File.content_hash.is_not(None),
            (FileText.file_id.is_(None)) | (FileText.content_hash != File.content_hash),
        )
        .order_by(File.created_at)
        .limit(limit)
    )


def _store(db: Session, file: File, status: str, text: str = "") -> None:
    row = db.get(FileText, file.id)
    if row is None:
        row = FileText(file_id=file.id)
        db.add(row)
    row.content_hash = file.content_hash
    row.status = status
    row.text = text
    row.extracted_at = datetime.now(UTC)


def index_file(db: Session, file: File) -> str:
    """Index one file's current content. Returns "ok", "skipped" or "failed"."""
    kind = text_extract.kind_of(file.name, file.mime_type)
    if kind is None or (file.size or 0) > text_extract.MAX_PARSED_BYTES:
        _store(db, file, "skipped")
        return "skipped"
    staged = None
    try:
        staged = file_service.prepare_download(file)
        text = text_extract.extract_text(staged, file.name, file.mime_type, file.size or 0)
    except Exception as exc:  # a damaged file or an unavailable object must not stop the rest
        logger.info("index: could not read %s: %s", file.id, exc)
        _store(db, file, "failed")
        return "failed"
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    if text is None:
        _store(db, file, "skipped")
        return "skipped"
    _store(db, file, "ok", text)
    return "ok"


def index_pending(db: Session, limit: int = 25) -> dict[str, int]:
    """Index up to `limit` files that need it. Returns how many ended up in each state."""
    counts = {"ok": 0, "skipped": 0, "failed": 0}
    for file in db.execute(_pending_query(limit)).scalars().all():
        counts[index_file(db, file)] += 1
        db.commit()
    return counts


def reset_index(db: Session) -> None:
    db.execute(delete(FileText))
    db.commit()


def pending_count(db: Session) -> int:
    subquery = _pending_query(1_000_000_000).subquery()
    return db.execute(select(func.count()).select_from(subquery)).scalar_one()


def snippet(text: str, query: str) -> str:
    """A short piece of `text` around the first place the query (or one of its words) appears."""
    flat = re.sub(r"\s+", " ", text).strip()
    lowered = flat.lower()
    needle = query.lower().strip()
    position = lowered.find(needle)
    if position < 0:
        for word in needle.split():
            position = lowered.find(word)
            if position >= 0:
                break
    if position < 0:
        return flat[: SNIPPET_CONTEXT * 2]
    start = max(0, position - SNIPPET_CONTEXT)
    end = min(len(flat), position + len(needle) + SNIPPET_CONTEXT)
    return ("..." if start else "") + flat[start:end] + ("..." if end < len(flat) else "")


def search_content(
    db: Session, owner: User, query: str, exclude: set[uuid.UUID] | None = None, limit: int = 30
) -> list[tuple[File, str]]:
    """Files whose text contains the query, best first, each with a snippet."""
    statement = (
        select(File, FileText.text)
        .join(FileText, FileText.file_id == File.id)
        .where(
            File.owner_id == owner.id,
            File.deleted_at.is_(None),
            FileText.status == "ok",
            FileText.content_hash == File.content_hash,
        )
    )
    if exclude:
        statement = statement.where(File.id.not_in(exclude))
    if db.get_bind().dialect.name == "postgresql":
        vector = func.to_tsvector("simple", FileText.text)
        tsquery = func.plainto_tsquery("simple", query)
        statement = statement.where(vector.op("@@")(tsquery)).order_by(
            func.ts_rank(vector, tsquery).desc()
        )
    else:
        statement = statement.where(FileText.text.icontains(query, autoescape=True)).order_by(
            File.name
        )
    rows = db.execute(statement.limit(limit)).all()
    return [(file, snippet(text, query)) for file, text in rows]
