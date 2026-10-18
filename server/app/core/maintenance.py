"""Periodic housekeeping that runs inside the backend process (Phase 10-lite).

Today that is one job: deleting chunked-upload sessions that were abandoned
(past their `expires_at`) together with their temporary chunks on disk.
`upload_service.sweep_expired_uploads` has existed since Phase 5 but nothing
called it; this loop does, with no cron job or extra container to set up.

Failures are logged and the loop carries on - housekeeping must never take the
API down, and a missed run is simply retried at the next interval.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.core import database
from app.core.config import get_settings
from app.services import gc_service, index_service, media_cache, thumbnail_service, upload_service
from app.services.storage_service import get_storage_service

logger = logging.getLogger(__name__)

# The first garbage-collection pass is one interval after the backend starts (not at startup, when
# the engine may still be coming up), then once per interval.
_last_gc = time.monotonic()


def _gc_due() -> bool:
    settings = get_settings()
    interval = settings.gc_interval_hours * 3600
    return settings.gc_enabled and (time.monotonic() - _last_gc) >= interval


def run_maintenance_once(session_factory: Callable[[], Session] | None = None) -> dict[str, int]:
    """Runs every housekeeping job once. Returns what each one did."""
    factory = session_factory or database.SessionLocal
    db = factory()
    try:
        swept = upload_service.sweep_expired_uploads(db)
        if swept:
            logger.info("maintenance: removed %d expired upload session(s)", swept)
        evicted = media_cache.evict_old()
        if evicted:
            logger.info("maintenance: removed %d stale preview cache file(s)", evicted)
        result = {"uploads_swept": swept, "preview_cache_evicted": evicted}
        if _gc_due():
            global _last_gc
            _last_gc = time.monotonic()
            settings = get_settings()
            report = gc_service.run_gc(
                db,
                get_storage_service(),
                Path(settings.storage_root),
                delete=settings.gc_delete_enabled,
                grace_hours=settings.gc_grace_hours,
            )
            result["gc_orphans"] = report.orphan_objects
        return result
    except Exception:
        db.rollback()
        logger.exception("maintenance run failed; will retry at the next interval")
        return {}
    finally:
        db.close()


def run_index_once(session_factory: Callable[[], Session] | None = None) -> dict[str, int]:
    """Indexes the text of a few new or changed files (search inside documents)."""
    db = (session_factory or database.SessionLocal)()
    try:
        counts = index_service.index_pending(db, get_settings().index_batch)
        if any(counts.values()):
            logger.info("index: %s", counts)
        return counts
    except Exception:
        db.rollback()
        logger.exception("indexing failed; will retry at the next interval")
        return {}
    finally:
        db.close()


def run_thumbnails_once(session_factory: Callable[[], Session] | None = None) -> int:
    """Makes a few thumbnails ahead of time; returns how many it made."""
    db = (session_factory or database.SessionLocal)()
    try:
        return thumbnail_service.pregenerate(db, get_settings().thumb_batch)
    except Exception:
        db.rollback()
        logger.exception("thumbnail pre-generation failed; will retry at the next interval")
        return 0
    finally:
        db.close()


async def thumbnail_loop(interval_seconds: float) -> None:
    """Works through the photo library a few thumbnails at a time, resting when it is caught up."""
    while True:
        await asyncio.sleep(interval_seconds)
        made = await asyncio.to_thread(run_thumbnails_once)
        if made == 0:
            await asyncio.sleep(max(interval_seconds, 60))  # caught up: check less often


async def index_loop(interval_seconds: float) -> None:
    """Keeps the search index current, a small batch at a time."""
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(run_index_once)


async def maintenance_loop(interval_seconds: float) -> None:
    """Runs `run_maintenance_once` every `interval_seconds` until cancelled."""
    while True:
        await asyncio.sleep(interval_seconds)
        # The sweep does blocking database and HTTP work; keep it off the event loop.
        await asyncio.to_thread(run_maintenance_once)
