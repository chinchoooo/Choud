"""Command line: `cloudsync login | sync | run | status | logout`.

cloudsync login --server http://100.64.0.5 --email me@example.com --folder ~/CloudSync
cloudsync sync      # one pass, then exit (good for cron / testing)
cloudsync run       # keep the folder in sync until interrupted
cloudsync status    # what is pending, and why
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

import httpx

from . import __version__
from .api import ApiClient, ApiError, ApiUnavailable, AuthError
from .config import Config, load_config, save_config
from .database import StateDB
from .syncer import SyncEngine, SyncReport
from .watcher import Debouncer, FolderWatcher

log = logging.getLogger("cloudsync")

EXIT_OK, EXIT_ERRORS, EXIT_OFFLINE, EXIT_AUTH, EXIT_USAGE = 0, 1, 2, 3, 64
OFFLINE_RETRY_SECONDS = 30.0


def build_engine(
    config: Config, config_dir: Path | None = None, http: httpx.Client | None = None
) -> SyncEngine:
    """Wire a SyncEngine from saved configuration."""

    def remember_tokens(access: str, refresh: str) -> None:
        config.access_token, config.refresh_token = access, refresh
        save_config(config, config_dir)

    api = ApiClient(
        config.server_url,
        http=http,
        access_token=config.access_token,
        refresh_token=config.refresh_token,
        on_tokens=remember_tokens,
    )
    db = StateDB(config.state_dir / "state.db")
    return SyncEngine(
        config.root,
        api,
        db,
        settle_seconds=config.settle_seconds,
        chunk_threshold=config.chunk_threshold,
        chunk_size=config.chunk_size,
    )


def exit_code(report: SyncReport) -> int:
    if report.auth_required:
        return EXIT_AUTH
    if report.offline:
        return EXIT_OFFLINE
    return EXIT_ERRORS if report.errors else EXIT_OK


def run_forever(
    engine: SyncEngine,
    config: Config,
    stop: threading.Event,
    *,
    watcher_factory=FolderWatcher,
    clock=time.monotonic,
) -> int:
    """Sync, then wait for a local change (debounced) or the poll interval, repeatedly."""
    debouncer = Debouncer(config.debounce_seconds, clock)
    watcher = watcher_factory(config.root, debouncer)
    watcher.start()
    code = EXIT_OK
    try:
        while not stop.is_set():
            report = engine.sync_until_quiet()
            log.info("sync: %s", report.summary())
            for error in report.errors:
                log.warning("  %s", error)
            for path, reason in report.skipped.items():
                log.warning("  skipped %s: %s", path, reason)
            if report.auth_required:
                return EXIT_AUTH
            code = exit_code(report)

            wait = OFFLINE_RETRY_SECONDS if report.offline else config.poll_interval
            deadline = clock() + wait
            debouncer.reset()
            while not stop.is_set() and clock() < deadline:
                if debouncer.ready():
                    break  # something changed locally and has settled: sync now
                stop.wait(min(0.25, max(0.01, deadline - clock())))
    finally:
        watcher.stop()
        engine.db.close()
    return code


# --- commands --------------------------------------------------------------------------


def cmd_login(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    server = (args.server or config.server_url).rstrip("/")
    email = args.email or config.email
    folder = Path(args.folder or config.sync_root or Path.home() / "CloudSync").expanduser()
    if not server or not email:
        print("--server and --email are required the first time.", file=sys.stderr)
        return EXIT_USAGE

    password = os.environ.get("CLOUDSYNC_PASSWORD") or getpass.getpass(f"Password for {email}: ")
    config.server_url, config.email, config.sync_root = server, email, str(folder.resolve())

    def remember(access: str, refresh: str) -> None:
        config.access_token, config.refresh_token = access, refresh

    api = ApiClient(server, http=http, on_tokens=remember)
    try:
        api.login(email, password)
    except AuthError:
        print("Login failed: wrong email or password.", file=sys.stderr)
        return EXIT_AUTH
    except ApiUnavailable as exc:
        print(f"Could not reach {server}: {exc}", file=sys.stderr)
        return EXIT_OFFLINE
    except ApiError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return EXIT_ERRORS

    folder.mkdir(parents=True, exist_ok=True)
    path = save_config(config, config_dir)
    print(f"Logged in as {email}. Syncing {folder}\nSettings saved to {path}")
    return EXIT_OK


def _require_login(config: Config) -> bool:
    if not config.is_logged_in or not config.sync_root:
        print("Not logged in. Run `cloudsync login` first.", file=sys.stderr)
        return False
    return True


def cmd_sync(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    if not _require_login(config):
        return EXIT_USAGE
    engine = build_engine(config, config_dir, http)
    try:
        report = engine.sync_until_quiet()
    finally:
        engine.db.close()
    print(report.summary())
    for error in report.errors:
        print(f"  error: {error}", file=sys.stderr)
    for path, reason in report.skipped.items():
        print(f"  skipped {path}: {reason}", file=sys.stderr)
    return exit_code(report)


def cmd_run(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    if not _require_login(config):
        return EXIT_USAGE
    engine = build_engine(config, config_dir, http)
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    print(f"Syncing {config.root} with {config.server_url} - press Ctrl+C to stop.")
    return run_forever(engine, config, stop)


def cmd_status(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    if not _require_login(config):
        return EXIT_USAGE
    print(f"Server : {config.server_url}")
    print(f"Account: {config.email}")
    print(f"Folder : {config.root}")
    db_path = config.state_dir / "state.db"
    if not db_path.exists():
        print("Never synced yet.")
        return EXIT_OK
    db = StateDB(db_path)
    try:
        print(f"Tracked files: {len(db.all_entries())}")
        items = db.queue_items()
        if not items:
            print("Nothing pending.")
        else:
            print(f"Pending ({len(items)}):")
            for item in items:
                retry = ""
                if item.attempts:
                    wait = max(0, int(item.next_attempt - time.time()))
                    retry = f"  [attempt {item.attempts}, retry in {wait}s: {item.last_error}]"
                print(f"  {item.kind:14} {item.path}{retry}")
    finally:
        db.close()
    return EXIT_OK


def cmd_logout(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    config.access_token = config.refresh_token = ""
    save_config(config, config_dir)
    print("Logged out. Your files and sync history were left untouched.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloudsync", description="Personal Cloud sync client")
    parser.add_argument("--version", action="version", version=f"cloudsync {__version__}")
    parser.add_argument(
        "--config-dir", type=Path, help="where settings are stored (default: per-user)"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="log in and choose the folder to sync")
    login.add_argument("--server", help="e.g. http://100.64.0.5 (the server's Tailscale address)")
    login.add_argument("--email")
    login.add_argument("--folder", help="folder to keep in sync (default: ~/CloudSync)")
    login.set_defaults(func=cmd_login)

    sub.add_parser("sync", help="sync once and exit").set_defaults(func=cmd_sync)
    sub.add_parser("run", help="keep syncing until stopped").set_defaults(func=cmd_run)
    sub.add_parser("status", help="show what is pending").set_defaults(func=cmd_status)
    sub.add_parser("logout", help="forget the saved login").set_defaults(func=cmd_logout)
    return parser


def _make_output_safe() -> None:
    """Never crash because a file name cannot be printed.

    A Windows console often uses a legacy code page (cp1252). A file called
    `日本語.txt` in an error or "skipped" message would raise UnicodeEncodeError and
    kill the client. Unprintable characters are replaced instead.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")


def main(argv: Sequence[str] | None = None, *, http: httpx.Client | None = None) -> int:
    _make_output_safe()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return args.func(args, args.config_dir, http)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
