"""Decide what to do for every path: the three-way comparison.

For each path there are three views of the file:

    L  local      what is on disk right now          (scanner)
    R  remote     what the server has right now      (snapshot)
    B  base       what both agreed on at the last sync (state database)

Comparing L and R against B tells us who changed what, which is the only way to
tell "I edited it" from "someone else edited it" from "both of us did". Nothing
here touches the disk or the network: `decide` is a pure function of its three
arguments, which is what makes the whole table exhaustively testable.

The rules (a missing view is "-"):

    L  R  B   situation                          action
    -  -  -   (not a file anywhere)              nothing
    -  -  B   gone on both sides                 FORGET   drop the stale base
    L  -  -   new here                           UPLOAD_NEW
    -  R  -   new on the server                  DOWNLOAD
    L  -  B   L unchanged: deleted on the server DELETE_LOCAL   (moved to local trash)
    L  -  B   L edited: server deleted it        UPLOAD_NEW     (our edit wins over a delete)
    -  R  B   R unchanged: deleted here          DELETE_REMOTE  (server trash, conditional)
    -  R  B   R edited: we deleted it            DOWNLOAD       (their edit wins over a delete)
    L  R  -   same bytes                         ADOPT
    L  R  -   different bytes                    CONFLICT
    L  R  B   same bytes                         ADOPT (or nothing if already recorded)
    L  R  B   only we changed                    UPLOAD_UPDATE  (conditional on B's version)
    L  R  B   only the server changed            DOWNLOAD
    L  R  B   both changed                       CONFLICT       (keep both, never overwrite)

Whenever a delete races an edit, the edit wins: a delete can be redone, lost
work cannot (Rule 5: never silently destroy data).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .api import RemoteFile, RemoteSnapshot
from .database import Entry
from .paths import path_problem
from .scanner import LocalFile, ScanResult


class Kind(str, Enum):
    DOWNLOAD = "download"
    CONFLICT = "conflict"
    ADOPT = "adopt"
    UPLOAD_NEW = "upload_new"
    UPLOAD_UPDATE = "upload_update"
    DELETE_LOCAL = "delete_local"
    DELETE_REMOTE = "delete_remote"
    FORGET = "forget"


# Execution order: bring server changes down first, then push ours, then delete.
_ORDER = {kind: i for i, kind in enumerate(Kind)}


@dataclass(frozen=True)
class Action:
    kind: Kind
    path: str
    local: LocalFile | None = None
    remote: RemoteFile | None = None
    base: Entry | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind.value, self.path)


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    mkdir_local: list[str] = field(default_factory=list)
    mkdir_remote: list[str] = field(default_factory=list)
    # Paths left alone this cycle, with the reason (collisions, illegal names, ...).
    skipped: dict[str, str] = field(default_factory=dict)


def decide(local: LocalFile | None, remote: RemoteFile | None, base: Entry | None) -> Kind | None:
    """What to do for one path, or None if it is already in sync."""
    if local and remote:
        if local.content_hash == remote.content_hash:
            already_recorded = (
                base is not None
                and base.file_id == remote.id
                and base.version_id == remote.version_id
                and base.content_hash == local.content_hash
            )
            return None if already_recorded else Kind.ADOPT
        if base is None:
            return Kind.CONFLICT  # created independently on both sides
        local_changed = local.content_hash != base.content_hash
        server_changed = remote.version_id != base.version_id or remote.id != base.file_id
        if local_changed and server_changed:
            return Kind.CONFLICT
        if local_changed:
            return Kind.UPLOAD_UPDATE
        if server_changed:
            return Kind.DOWNLOAD
        # Neither side moved from the base, yet they differ: the base is stale or
        # corrupt. Keep both rather than guess which one is right.
        return Kind.CONFLICT

    if local:
        if base is not None and local.content_hash == base.content_hash:
            return Kind.DELETE_LOCAL
        return Kind.UPLOAD_NEW

    if remote:
        if base is not None and remote.id == base.file_id and remote.version_id == base.version_id:
            return Kind.DELETE_REMOTE
        return Kind.DOWNLOAD

    return Kind.FORGET if base is not None else None


def _depth(path: str) -> int:
    return path.count("/")


def _ancestors(path: str) -> list[str]:
    parts = path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def plan(scan: ScanResult, remote: RemoteSnapshot, base: dict[str, Entry]) -> Plan:
    """Build the full plan for one sync cycle."""
    result = Plan()

    # A file and a folder can share a path (the server allows it, a disk does
    # not). Neither side's entry at such a path can be synced safely, so they
    # are skipped and reported.
    blocked: dict[str, str] = {}
    for path in set(scan.files) & set(remote.folders):
        blocked[path] = "a local file and a server folder have the same path"
    for path in set(remote.files) & set(scan.dirs):
        blocked[path] = "a server file and a local folder have the same path"
    for path in set(remote.files) & set(remote.folders):
        blocked[path] = "the server has a file and a folder with the same path"
    for path in set(scan.files) & set(scan.dirs):
        blocked[path] = "path is both a file and a folder"

    def blocked_reason(path: str) -> str | None:
        if path in blocked:
            return blocked[path]
        for ancestor in _ancestors(path):
            if ancestor in blocked:
                return f"inside a blocked path ({ancestor})"
        return None

    unstable = scan.unstable
    all_paths = set(scan.files) | set(remote.files) | set(base) | unstable

    for path in sorted(all_paths):
        if path in unstable:
            continue  # still being written: decide next cycle
        reason = blocked_reason(path)
        if reason:
            result.skipped[path] = reason
            continue
        problem = path_problem(path)
        if problem and path not in scan.files:
            # A server file whose name this machine cannot hold. Leave it
            # remote-only (and do not mistake its absence for a local delete).
            result.skipped[path] = problem
            continue

        local = scan.files.get(path)
        remote_file = remote.files.get(path)
        entry = base.get(path)
        kind = decide(local, remote_file, entry)
        if kind is not None:
            result.actions.append(
                Action(kind=kind, path=path, local=local, remote=remote_file, base=entry)
            )

    for path in sorted(remote.folders, key=lambda p: (_depth(p), p)):
        if path in scan.dirs or path in blocked or blocked_reason(path) or path_problem(path):
            continue
        result.mkdir_local.append(path)
    for path in sorted(scan.dirs, key=lambda p: (_depth(p), p)):
        if path in remote.folders or path in blocked or blocked_reason(path):
            continue
        result.mkdir_remote.append(path)

    result.actions.sort(key=lambda a: (_ORDER[a.kind], a.path))
    return result
