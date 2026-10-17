"""Backup mode: quietly copy chosen folders to the server whenever it is reachable.

Unlike `sync`, a backup never downloads and never deletes anything on the server (see
`syncer.backup_plan`). It is meant for a single laptop that should be saved to the home
server whenever it is on the VPN: it waits while the server is out of reach, then uploads what
is new or changed, at low priority, and goes quiet again.

Each folder is backed up under `Backups/<device name>/<folder name>` on the server and keeps its
bookkeeping in the settings directory, so nothing is ever written inside the folders themselves.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import Config

log = logging.getLogger("cloudsync")

UNREACHABLE_RETRY_SECONDS = 60.0


@dataclass(frozen=True)
class BackupTarget:
    folder: Path
    remote_prefix: str
    state_dir: Path


def _clean(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "folder"


def default_device_name() -> str:
    return _clean(socket.gethostname())


def backup_targets(config: Config, config_dir: Path) -> list[BackupTarget]:
    """One target per configured folder, with a unique, stable server path and state folder."""
    device = _clean(config.device_name or default_device_name())
    used: set[str] = set()
    targets = []
    for raw in config.backup_folders:
        folder = Path(raw)
        name = _clean(folder.name or folder.anchor or "root")
        unique = name
        counter = 2
        while unique.lower() in used:
            unique = f"{name} ({counter})"
            counter += 1
        used.add(unique.lower())
        digest = hashlib.sha1(str(folder).encode("utf-8")).hexdigest()[:12]  # noqa: S324
        targets.append(
            BackupTarget(
                folder=folder,
                remote_prefix=f"Backups/{device}/{unique}",
                state_dir=config_dir / "backup-state" / digest,
            )
        )
    return targets


def lower_priority() -> None:
    """Run at the lowest CPU and disk priority so a backup never slows the machine down."""
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetCurrentProcess()
            kernel32.SetPriorityClass(handle, 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
            kernel32.SetPriorityClass(handle, 0x00100000)  # PROCESS_MODE_BACKGROUND_BEGIN (disk)
        else:
            os.nice(10)
            subprocess.run(  # best effort: idle disk priority where ionice exists
                ["ionice", "-c3", "-p", str(os.getpid())],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as exc:  # never fail a backup because priorities could not be lowered
        log.debug("could not lower priority: %s", exc)


def run_backup_forever(engines, config: Config, stop: threading.Event, *, reachable) -> int:
    """Backup loop: while the server is reachable, back up every folder, then rest.

    `engines` is a list of (label, SyncEngine); `reachable()` says whether the server answers.
    Returns an exit code (3 if the login expired, otherwise 0 when asked to stop).
    """
    from .main import EXIT_AUTH, EXIT_OK  # local import: main imports this module

    was_reachable: bool | None = None
    try:
        while not stop.is_set():
            if not reachable():
                if was_reachable is not False:
                    log.info("server not reachable (is Tailscale connected?): waiting")
                was_reachable = False
                stop.wait(UNREACHABLE_RETRY_SECONDS)
                continue
            if was_reachable is False:
                log.info("server reachable again: backing up")
            was_reachable = True

            for label, engine in engines:
                if stop.is_set():
                    break
                report = engine.sync_until_quiet()
                log.info("backup %s: %s", label, report.summary())
                for error in report.errors:
                    log.warning("  %s", error)
                if report.auth_required:
                    return EXIT_AUTH
                if report.offline:
                    was_reachable = False
                    break
            stop.wait(config.backup_interval)
    finally:
        for _, engine in engines:
            engine.db.close()
    return EXIT_OK
