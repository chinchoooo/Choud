"""One sync cycle, end to end: scan -> snapshot -> plan -> queue -> execute.

This is where the pieces meet. The decisions come from `reconciler` (pure
logic); this module does the I/O and the bookkeeping:

- It never lets one bad file stop the rest: each action has its own error
  handling and back-off, recorded in the durable queue.
- If the server cannot be reached it switches to offline mode: nothing is lost,
  local changes simply stay pending (visible in the queue, picked up again by the
  next cycle because every cycle is recomputed from disk + the state database).
- Conflicts keep both versions; deletes go to a recoverable trash.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .api import (
    ApiClient,
    ApiError,
    ApiUnavailable,
    AuthError,
    RemoteFile,
    RemoteSnapshot,
    VersionConflict,
)
from .conflicts import conflict_path
from .database import Entry, StateDB
from .downloader import ChangedDuringTransfer, download_file, move_to_local_trash
from .paths import INTERNAL_DIR, UnsafePathError, safe_join, split_parent
from .reconciler import Action, Kind, Plan, plan
from .scanner import ScanResult, scan
from .uploader import FileChangedLocally, upload_file

MAX_BACKOFF_SECONDS = 300.0


@dataclass
class SyncReport:
    uploaded: int = 0
    downloaded: int = 0
    deleted_local: int = 0
    deleted_remote: int = 0
    conflicts: int = 0
    adopted: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    unstable: int = 0
    deferred: int = 0
    pending: int = 0
    offline: bool = False
    auth_required: bool = False

    @property
    def did_work(self) -> bool:
        return bool(
            self.uploaded
            + self.downloaded
            + self.deleted_local
            + self.deleted_remote
            + self.conflicts
            + self.adopted
        )

    def merge(self, other: SyncReport) -> None:
        for name in ("uploaded", "downloaded", "deleted_local", "deleted_remote", "conflicts"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.adopted += other.adopted
        self.errors = other.errors
        self.skipped = other.skipped
        self.unstable = other.unstable
        self.deferred = other.deferred
        self.pending = other.pending
        self.offline = other.offline
        self.auth_required = other.auth_required

    def summary(self) -> str:
        if self.auth_required:
            return "login expired - run `cloudsync login` again"
        if self.offline:
            return f"offline - {self.pending} change(s) waiting to sync"
        parts = [
            f"{self.uploaded} uploaded",
            f"{self.downloaded} downloaded",
            f"{self.deleted_local} removed locally",
            f"{self.deleted_remote} removed on server",
            f"{self.conflicts} conflict(s)",
        ]
        text = ", ".join(parts)
        if self.errors:
            text += f"; {len(self.errors)} error(s)"
        if self.pending:
            text += f"; {self.pending} pending"
        return text


_BACKUP_KEEPS = {Kind.UPLOAD_NEW, Kind.UPLOAD_UPDATE, Kind.ADOPT, Kind.FORGET}


def backup_plan(the_plan: Plan) -> Plan:
    """Narrow a normal plan to what a one-way backup may do.

    Downloads and every kind of delete are dropped. A conflict (the server copy changed too)
    becomes a new version uploaded from this machine, so nothing is overwritten or lost.
    """
    kept: list[Action] = []
    for action in the_plan.actions:
        if action.kind is Kind.CONFLICT:
            kept.append(Action(Kind.UPLOAD_UPDATE, action.path, action.local, action.remote, None))
        elif action.kind in _BACKUP_KEEPS:
            kept.append(action)
    the_plan.actions = kept
    the_plan.mkdir_local = []
    return the_plan


class SyncEngine:
    def __init__(
        self,
        root: Path,
        api: ApiClient,
        db: StateDB,
        *,
        settle_seconds: float = 2.0,
        chunk_threshold: int = 20 * 1024 * 1024,
        chunk_size: int = 5 * 1024 * 1024,
        now: Callable[[], float] = time.time,
        today: Callable[[], _dt.date] = _dt.date.today,
        mode: str = "sync",
        state_dir: Path | None = None,
    ) -> None:
        self.root = root
        self.api = api
        self.db = db
        self.settle_seconds = settle_seconds
        self.chunk_threshold = chunk_threshold
        self.chunk_size = chunk_size
        self._now = now
        self._today = today
        # "backup" = upload only: never download, never delete anywhere, and when both sides
        # changed this machine wins by adding a new version (the old one stays in history).
        self.mode = mode
        self.state_dir = state_dir or root / INTERNAL_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "tmp").mkdir(parents=True, exist_ok=True)

    # --- public ------------------------------------------------------------

    def sync_until_quiet(self, max_passes: int = 4) -> SyncReport:
        """Run cycles until one changes nothing (e.g. a conflict copy created by one
        cycle is uploaded by the next). Stops early when offline or logged out."""
        total = SyncReport()
        for _ in range(max_passes):
            report = self.sync_once()
            total.merge(report)
            if report.offline or report.auth_required or not report.did_work:
                break
        return total

    def sync_once(self) -> SyncReport:
        report = SyncReport()
        scanned = scan(self.root, self.db, settle_seconds=self.settle_seconds, now=self._now)
        report.unstable = len(scanned.unstable)
        report.skipped = dict(scanned.problems)

        try:
            remote = self.api.snapshot()
        except ApiUnavailable:
            report.offline = True
            self._record_offline_queue(scanned)
            report.pending = len(self.db.queue_items())
            return report
        except AuthError:
            report.auth_required = True
            return report

        base = self.db.all_entries()
        the_plan = plan(scanned, remote, base)
        if self.mode == "backup":
            the_plan = backup_plan(the_plan)
        report.skipped.update(the_plan.skipped)
        self.db.replace_queue([a.key for a in the_plan.actions], self._now())

        self._make_local_dirs(the_plan, report)
        self._run_actions(the_plan, scanned, remote, report)
        if not report.offline and not report.auth_required:
            self._make_remote_dirs(the_plan, report)

        report.pending = len(self.db.queue_items())
        return report

    # --- offline bookkeeping ---------------------------------------------------

    def _record_offline_queue(self, scanned: ScanResult) -> None:
        """Without a snapshot we can't decide, but we can still note what is waiting."""
        base = self.db.all_entries()
        keys = []
        for path, local in scanned.files.items():
            entry = base.get(path)
            if entry is None:
                keys.append((Kind.UPLOAD_NEW.value, path))
            elif entry.content_hash != local.content_hash:
                keys.append((Kind.UPLOAD_UPDATE.value, path))
        for path in base:
            if self.mode == "backup":
                break  # a file deleted here is never deleted on the server
            if path not in scanned.files and path not in scanned.unstable:
                keys.append((Kind.DELETE_REMOTE.value, path))
        self.db.replace_queue(keys, self._now())

    # --- directories -------------------------------------------------------------

    def _make_local_dirs(self, the_plan: Plan, report: SyncReport) -> None:
        for rel in the_plan.mkdir_local:
            try:
                safe_join(self.root, rel).mkdir(parents=True, exist_ok=True)
            except (OSError, UnsafePathError) as exc:
                report.errors.append(f"could not create folder {rel}: {exc}")

    def _make_remote_dirs(self, the_plan: Plan, report: SyncReport) -> None:
        for rel in the_plan.mkdir_remote:
            try:
                self.api.ensure_folder(rel)
            except ApiUnavailable:
                report.offline = True
                return
            except ApiError as exc:
                report.errors.append(f"could not create server folder {rel}: {exc}")

    # --- actions -------------------------------------------------------------------

    def _run_actions(
        self, the_plan: Plan, scanned: ScanResult, remote: RemoteSnapshot, report: SyncReport
    ) -> None:
        folder_ids: dict[str, str | None] = {}
        taken_conflict_names: set[str] = set()

        for action in the_plan.actions:
            item = self.db.queue_get(*action.key)
            if item and item.next_attempt > self._now():
                report.deferred += 1  # backing off after earlier failures
                continue
            try:
                self._run(action, scanned, remote, folder_ids, taken_conflict_names, report)
                self.db.queue_done(*action.key)
            except ApiUnavailable:
                report.offline = True
                return
            except AuthError:
                report.auth_required = True
                return
            except VersionConflict:
                # Somebody changed it between our snapshot and our write. Nothing
                # was applied; the next cycle sees the new state and resolves it
                # (usually as a conflict copy). No back-off: retry straight away.
                self.db.queue_failed(*action.key, "changed on the server meanwhile", self._now())
            except (ApiError, ChangedDuringTransfer, FileChangedLocally) as exc:
                self._fail(action, str(exc), report)
            except (OSError, UnsafePathError) as exc:
                self._fail(action, f"{type(exc).__name__}: {exc}", report)

    def _fail(self, action: Action, message: str, report: SyncReport) -> None:
        item = self.db.queue_get(*action.key)
        attempts = (item.attempts if item else 0) + 1
        delay = min(MAX_BACKOFF_SECONDS, 5.0 * 2 ** (attempts - 1))
        self.db.queue_failed(*action.key, message, self._now() + delay)
        report.errors.append(f"{action.kind.value} {action.path}: {message}")

    def _folder_id(self, folder_path: str, cache: dict[str, str | None]) -> str | None:
        if folder_path not in cache:
            cache[folder_path] = self.api.ensure_folder(folder_path)
        return cache[folder_path]

    def _record(
        self, path: str, file_id: str, digest: str, version_id: str | None, size: int, mtime: int
    ) -> None:
        self.db.put_entry(Entry(path, file_id, digest, version_id, size, mtime))

    def _run(
        self,
        action: Action,
        scanned: ScanResult,
        remote: RemoteSnapshot,
        folder_ids: dict[str, str | None],
        taken: set[str],
        report: SyncReport,
    ) -> None:
        path, kind = action.path, action.kind
        local, remote_file, base = action.local, action.remote, action.base

        if kind is Kind.DOWNLOAD:
            self._download(path, remote_file)
            report.downloaded += 1

        elif kind is Kind.CONFLICT:
            # Keep BOTH versions: the local edit moves to a conflict copy, the
            # server's version takes the original path. Both then sync normally.
            def in_use(candidate: str) -> bool:
                return (
                    candidate in taken
                    or candidate in scanned.files
                    or candidate in remote.files
                    or safe_join(self.root, candidate).exists()
                )

            copy = conflict_path(path, in_use, self._today())
            taken.add(copy)
            os.replace(safe_join(self.root, path), safe_join(self.root, copy))
            self.db.delete_entry(path)
            self._download(path, remote_file)
            report.conflicts += 1

        elif kind is Kind.ADOPT:
            self._record(
                path, remote_file.id, local.content_hash, remote_file.version_id,
                local.size, local.mtime_ns,
            )  # fmt: skip
            report.adopted += 1

        elif kind in (Kind.UPLOAD_NEW, Kind.UPLOAD_UPDATE):
            parent, _ = split_parent(path)
            folder_id = self._folder_id(parent, folder_ids)
            expect_new = kind is Kind.UPLOAD_NEW
            base_version = None
            if not expect_new:
                base_version = (base.version_id if base else None) or (
                    remote_file.version_id if remote_file else None
                )
            result = upload_file(
                self.api,
                self.db,
                self.root,
                local,
                folder_id=folder_id,
                base_version_id=base_version,
                expect_new=expect_new,
                chunk_threshold=self.chunk_threshold,
                chunk_size=self.chunk_size,
            )
            # Remember what the server says it stored, with the scan-time stat.
            self._record(
                path, result.file_id, result.content_hash or local.content_hash,
                result.version_id, local.size, local.mtime_ns,
            )  # fmt: skip
            report.uploaded += 1

        elif kind is Kind.DELETE_LOCAL:
            move_to_local_trash(self.root, path, self.state_dir)
            self.db.delete_entry(path)
            report.deleted_local += 1

        elif kind is Kind.DELETE_REMOTE:
            self.api.delete_file(remote_file.id, remote_file.version_id)
            self.db.delete_entry(path)
            report.deleted_remote += 1

        elif kind is Kind.FORGET:
            self.db.delete_entry(path)

    def _download(self, path: str, remote_file: RemoteFile) -> None:
        got = download_file(self.api, self.root, path, remote_file, self.state_dir)
        self._record(
            path, remote_file.id, got.content_hash, remote_file.version_id, got.size, got.mtime_ns
        )
