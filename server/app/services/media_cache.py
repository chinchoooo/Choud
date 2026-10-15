"""A small on-disk cache of files being previewed.

Video players ask for a file in many byte ranges; copying the whole object out
of the engine for every range would be hopeless, so the first request stages it
here and later ranges reuse it. Entries older than `MAX_AGE_SECONDS` are removed
by the maintenance loop. Safe to delete at any time.
"""

import logging
import os
import time
from pathlib import Path

from app.core.config import get_settings
from app.models.file import File
from app.services import file_service

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_AGE_SECONDS = 3600


def cache_dir() -> Path:
    return Path(settings.storage_root) / "media-cache"


def cached_path(file: File) -> Path:
    """A readable copy of the file's current content (staged on first use)."""
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / str(file.content_hash)
    if target.exists():
        os.utime(target)  # keep it alive while it is being used
        return target
    staged = file_service.prepare_download(file)
    try:
        staged.replace(target)  # same volume: atomic
    except OSError:
        staged.unlink(missing_ok=True)
        raise
    return target


def evict_old(max_age_seconds: int = MAX_AGE_SECONDS) -> int:
    """Deletes cache entries not used for `max_age_seconds`. Returns how many."""
    directory = cache_dir()
    if not directory.is_dir():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for entry in directory.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            logger.warning("could not remove media cache entry %s", entry)
    return removed
