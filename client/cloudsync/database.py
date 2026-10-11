"""Local SQLite state: what was last in sync, what is queued, which uploads can resume.

This database is the client's memory. It lives *inside* the sync folder
(`.cloudsync/state.db`, never synced) so it always describes exactly that folder:
move or copy the folder together with its `.cloudsync` directory and the client
carries on where it left off; point it at a different folder and it starts
fresh. See docs/synchronization.md#desktop-client-architecture.

Three tables:

- `entries`  the *base* of the three-way comparison: for every synced file, the
             hash, server version and file id as of the last successful sync,
             plus the size/mtime used to avoid re-hashing unchanged files.
- `queue`    the operations the last reconcile decided on, so pending work
             survives a restart and shows up in `status` even while offline.
- `uploads`  chunked-upload sessions to resume after an interruption.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    path         TEXT PRIMARY KEY,
    file_id      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version_id   TEXT,
    size         INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS queue (
    kind         TEXT NOT NULL,
    path         TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    next_attempt REAL NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    PRIMARY KEY (kind, path)
);
CREATE TABLE IF NOT EXISTS uploads (
    path         TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    upload_id    TEXT NOT NULL,
    PRIMARY KEY (path, content_hash)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Entry:
    """A file as it was at the last successful sync (the three-way 'base')."""

    path: str
    file_id: str
    content_hash: str
    version_id: str | None
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class QueueItem:
    kind: str
    path: str
    attempts: int
    last_error: str | None
    next_attempt: float
    created_at: float


class StateDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        # WAL keeps the database consistent if the process is killed mid-write.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- entries -----------------------------------------------------------

    def get_entry(self, path: str) -> Entry | None:
        row = self._conn.execute("SELECT * FROM entries WHERE path = ?", (path,)).fetchone()
        return Entry(**dict(row)) if row else None

    def all_entries(self) -> dict[str, Entry]:
        rows = self._conn.execute("SELECT * FROM entries").fetchall()
        return {r["path"]: Entry(**dict(r)) for r in rows}

    def put_entry(self, entry: Entry) -> None:
        self._conn.execute(
            "INSERT INTO entries (path, file_id, content_hash, version_id, size, mtime_ns) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET file_id=excluded.file_id, "
            "content_hash=excluded.content_hash, version_id=excluded.version_id, "
            "size=excluded.size, mtime_ns=excluded.mtime_ns",
            (
                entry.path,
                entry.file_id,
                entry.content_hash,
                entry.version_id,
                entry.size,
                entry.mtime_ns,
            ),
        )
        self._conn.commit()

    def delete_entry(self, path: str) -> None:
        self._conn.execute("DELETE FROM entries WHERE path = ?", (path,))
        self._conn.commit()

    def update_stat(self, path: str, size: int, mtime_ns: int) -> None:
        """Refresh the cached size/mtime (e.g. after re-hashing identical content)."""
        self._conn.execute(
            "UPDATE entries SET size = ?, mtime_ns = ? WHERE path = ?", (size, mtime_ns, path)
        )
        self._conn.commit()

    # --- queue -------------------------------------------------------------

    def queue_items(self) -> list[QueueItem]:
        rows = self._conn.execute("SELECT * FROM queue ORDER BY created_at, path").fetchall()
        return [QueueItem(**dict(r)) for r in rows]

    def replace_queue(self, keys: Iterable[tuple[str, str]], now: float) -> None:
        """Make the queue hold exactly `keys` ((kind, path) pairs).

        Rows that are still wanted keep their attempt count and back-off, so a
        failing operation keeps backing off across re-plans instead of being
        retried at full speed every cycle. Rows no longer wanted (the situation
        changed) are dropped; new ones are added.
        """
        wanted = set(keys)
        existing = {(i.kind, i.path) for i in self.queue_items()}
        for kind, path in existing - wanted:
            self._conn.execute("DELETE FROM queue WHERE kind = ? AND path = ?", (kind, path))
        for kind, path in wanted - existing:
            self._conn.execute(
                "INSERT INTO queue (kind, path, created_at) VALUES (?, ?, ?)", (kind, path, now)
            )
        self._conn.commit()

    def queue_done(self, kind: str, path: str) -> None:
        self._conn.execute("DELETE FROM queue WHERE kind = ? AND path = ?", (kind, path))
        self._conn.commit()

    def queue_failed(self, kind: str, path: str, error: str, next_attempt: float) -> None:
        self._conn.execute(
            "UPDATE queue SET attempts = attempts + 1, last_error = ?, next_attempt = ? "
            "WHERE kind = ? AND path = ?",
            (error[:500], next_attempt, kind, path),
        )
        self._conn.commit()

    def queue_get(self, kind: str, path: str) -> QueueItem | None:
        row = self._conn.execute(
            "SELECT * FROM queue WHERE kind = ? AND path = ?", (kind, path)
        ).fetchone()
        return QueueItem(**dict(row)) if row else None

    # --- resumable uploads ---------------------------------------------------

    def get_upload(self, path: str, content_hash: str) -> str | None:
        row = self._conn.execute(
            "SELECT upload_id FROM uploads WHERE path = ? AND content_hash = ?",
            (path, content_hash),
        ).fetchone()
        return row["upload_id"] if row else None

    def put_upload(self, path: str, content_hash: str, upload_id: str) -> None:
        self._conn.execute(
            "INSERT INTO uploads (path, content_hash, upload_id) VALUES (?, ?, ?) "
            "ON CONFLICT(path, content_hash) DO UPDATE SET upload_id = excluded.upload_id",
            (path, content_hash, upload_id),
        )
        self._conn.commit()

    def delete_upload(self, path: str, content_hash: str) -> None:
        self._conn.execute(
            "DELETE FROM uploads WHERE path = ? AND content_hash = ?", (path, content_hash)
        )
        self._conn.commit()

    # --- meta ----------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()
