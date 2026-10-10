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
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core import database
from app.services import upload_service

logger = logging.getLogger(__name__)


def run_maintenance_once(session_factory: Callable[[], Session] | None = None) -> dict[str, int]:
    """Runs every housekeeping job once. Returns what each one did."""
    factory = session_factory or database.SessionLocal
    db = factory()
    try:
        swept = upload_service.sweep_expired_uploads(db)
        if swept:
            logger.info("maintenance: removed %d expired upload session(s)", swept)
        return {"uploads_swept": swept}
    except Exception:
        db.rollback()
        logger.exception("maintenance run failed; will retry at the next interval")
        return {}
    finally:
        db.close()


async def maintenance_loop(interval_seconds: float) -> None:
    """Runs `run_maintenance_once` every `interval_seconds` until cancelled."""
    while True:
        await asyncio.sleep(interval_seconds)
        # The sweep does blocking database and HTTP work; keep it off the event loop.
        await asyncio.to_thread(run_maintenance_once)
