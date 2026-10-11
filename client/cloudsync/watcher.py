"""Notice local changes quickly, without syncing on every keystroke.

Editors and downloads produce bursts of filesystem events (write temp file,
rename, touch...). `Debouncer` collapses a burst into one "something changed"
signal that fires only after things have been quiet for a moment.

The watcher is only a *hint* that makes sync feel immediate. Correctness never
depends on it: every cycle re-scans the folder and the periodic poll runs
regardless, so a missed event (a full event queue, a network drive that sends
none) only delays a sync, it cannot lose a change.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .paths import INTERNAL_DIR, is_ignored


class Debouncer:
    def __init__(self, quiet_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.quiet_seconds = quiet_seconds
        self._clock = clock
        self._last_event: float | None = None

    def poke(self) -> None:
        """Record a filesystem event."""
        self._last_event = self._clock()

    @property
    def dirty(self) -> bool:
        return self._last_event is not None

    def ready(self) -> bool:
        """True once events have happened and then stopped for `quiet_seconds`."""
        return (
            self._last_event is not None and self._clock() - self._last_event >= self.quiet_seconds
        )

    def reset(self) -> None:
        self._last_event = None


class _Handler(FileSystemEventHandler):
    def __init__(self, root: Path, debouncer: Debouncer) -> None:
        self._root = root.resolve()
        self._debouncer = debouncer

    def _relevant(self, raw_path: str | bytes | None) -> bool:
        if not raw_path:
            return False
        path = raw_path.decode() if isinstance(raw_path, bytes) else raw_path
        try:
            rel = Path(path).resolve().relative_to(self._root).as_posix()
        except (ValueError, OSError):
            return False
        # Our own staging area and editor temp files are not user changes.
        return rel != "." and not rel.startswith(INTERNAL_DIR) and not is_ignored(rel)

    def on_any_event(self, event: FileSystemEvent) -> None:
        if self._relevant(event.src_path) or self._relevant(getattr(event, "dest_path", None)):
            self._debouncer.poke()


class FolderWatcher:
    """Pokes a `Debouncer` whenever something inside `root` changes."""

    def __init__(self, root: Path, debouncer: Debouncer) -> None:
        self._observer = Observer()
        self._observer.schedule(_Handler(root, debouncer), str(root), recursive=True)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5)
