"""Command line: `cloudsync login | sync | run | status | folders | install-service | logout`.

cloudsync login --server http://100.64.0.5 --email me@example.com --folder ~/CloudSync
cloudsync login --mode backup --folder ~/Documents --folder ~/Pictures   # upload-only backup
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
from . import service as service_module
from .api import ApiClient, ApiError, ApiUnavailable, AuthError, TwoFactorRequired
from .backup import backup_targets, lower_priority, run_backup_forever
from .config import Config, default_config_dir, load_config, save_config
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


def build_backup_engines(
    config: Config, config_dir: Path | None = None, http: httpx.Client | None = None
) -> list:
    """One upload-only engine per backup folder, each scoped to its own server folder."""
    engines = []
    for target in backup_targets(config, config_dir or default_config_dir()):

        def remember_tokens(access: str, refresh: str) -> None:
            config.access_token, config.refresh_token = access, refresh
            save_config(config, config_dir)

        api = ApiClient(
            config.server_url,
            http=http,
            access_token=config.access_token,
            refresh_token=config.refresh_token,
            on_tokens=remember_tokens,
            remote_prefix=target.remote_prefix,
        )
        target.state_dir.mkdir(parents=True, exist_ok=True)
        engine = SyncEngine(
            target.folder,
            api,
            StateDB(target.state_dir / "state.db"),
            settle_seconds=config.settle_seconds,
            chunk_threshold=config.chunk_threshold,
            chunk_size=config.chunk_size,
            mode="backup",
            state_dir=target.state_dir,
        )
        engines.append((target.remote_prefix, engine))
    return engines


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
    mode = args.mode or config.mode
    chosen = [Path(f).expanduser() for f in (args.folder or [])]
    if mode == "backup":
        folders = chosen or [Path(f) for f in config.backup_folders]
        missing = [f for f in folders if not f.is_dir()]
        if not folders or missing:
            what = ", ".join(str(f) for f in missing) or "none given"
            print(f"Backup needs existing folders (--folder). Problem: {what}", file=sys.stderr)
            return EXIT_USAGE
        folder = folders[0]
    else:
        folders = []
        folder = (
            chosen[0] if chosen else Path(config.sync_root or Path.home() / "CloudSync")
        ).expanduser()
    if not server or not email:
        print("--server and --email are required the first time.", file=sys.stderr)
        return EXIT_USAGE

    password = os.environ.get("CLOUDSYNC_PASSWORD") or getpass.getpass(f"Password for {email}: ")
    config.server_url, config.email, config.mode = server, email, mode
    if mode == "backup":
        config.backup_folders = [str(f.resolve()) for f in folders]
        config.device_name = args.device_name or config.device_name
    else:
        config.sync_root = str(folder.resolve())

    def remember(access: str, refresh: str) -> None:
        config.access_token, config.refresh_token = access, refresh

    api = ApiClient(server, http=http, on_tokens=remember)
    otp = args.otp or os.environ.get("CLOUDSYNC_OTP")
    try:
        try:
            api.login(email, password, otp)
        except TwoFactorRequired:
            if otp or not sys.stdin.isatty():
                raise
            api.login(email, password, input("Two-factor code (or a recovery code): ").strip())
    except TwoFactorRequired:
        print("This account uses two-factor login: add --otp <code>.", file=sys.stderr)
        return EXIT_AUTH
    except AuthError as exc:
        if "email or password" in exc.detail:
            message = "wrong email or password."
        elif "not right" in exc.detail:
            message = "wrong two-factor code."
        else:
            message = exc.detail
        print(f"Login failed: {message}", file=sys.stderr)
        return EXIT_AUTH
    except ApiUnavailable as exc:
        print(f"Could not reach {server}: {exc}", file=sys.stderr)
        return EXIT_OFFLINE
    except ApiError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return EXIT_ERRORS

    if mode != "backup":
        folder.mkdir(parents=True, exist_ok=True)
    path = save_config(config, config_dir)
    if mode == "backup":
        print(
            f"Logged in as {email}. Backing up {len(folders)} folder(s) to {server}\n"
            f"Settings saved to {path}"
        )
        print("Run `cloudsync install-service` to back up automatically in the background.")
    else:
        print(f"Logged in as {email}. Syncing {folder}\nSettings saved to {path}")
    return EXIT_OK


def _require_login(config: Config) -> bool:
    if not config.is_logged_in or not config.has_folders:
        print("Not logged in. Run `cloudsync login` first.", file=sys.stderr)
        return False
    return True


def cmd_sync(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    if not _require_login(config):
        return EXIT_USAGE
    if config.mode == "backup":
        worst = EXIT_OK
        for label, engine in build_backup_engines(config, config_dir, http):
            try:
                report = engine.sync_until_quiet()
            finally:
                engine.db.close()
            print(f"{label}: {report.summary()}")
            for error in report.errors:
                print(f"  error: {error}", file=sys.stderr)
            worst = max(worst, exit_code(report))
        return worst
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
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    if config.mode == "backup":
        engines = build_backup_engines(config, config_dir, http)
        lower_priority()
        print(f"Backing up {len(engines)} folder(s) to {config.server_url} - press Ctrl+C to stop.")
        probe = engines[0][1].api
        return run_backup_forever(engines, config, stop, reachable=probe.reachable)
    engine = build_engine(config, config_dir, http)
    print(f"Syncing {config.root} with {config.server_url} - press Ctrl+C to stop.")
    return run_forever(engine, config, stop)


def cmd_status(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    if not _require_login(config):
        return EXIT_USAGE
    print(f"Server : {config.server_url}")
    print(f"Account: {config.email}")
    if config.mode == "backup":
        print(f"Mode   : backup (upload only) as device '{config.device_name or 'this computer'}'")
        for target in backup_targets(config, config_dir or default_config_dir()):
            db_file = target.state_dir / "state.db"
            if not db_file.exists():
                print(f"  {target.folder} -> {target.remote_prefix}: not backed up yet")
                continue
            db = StateDB(db_file)
            try:
                print(
                    f"  {target.folder} -> {target.remote_prefix}: "
                    f"{len(db.all_entries())} files saved, {len(db.queue_items())} waiting"
                )
            finally:
                db.close()
        return EXIT_OK
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


def cmd_folders(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    if config.mode != "backup":
        print(
            "Folders are only used in backup mode (`cloudsync login --mode backup`).",
            file=sys.stderr,
        )
        return EXIT_USAGE
    for raw in args.add or []:
        folder = Path(raw).expanduser()
        if not folder.is_dir():
            print(f"Not a folder: {folder}", file=sys.stderr)
            return EXIT_USAGE
        if str(folder.resolve()) not in config.backup_folders:
            config.backup_folders.append(str(folder.resolve()))
    for raw in args.remove or []:
        resolved = str(Path(raw).expanduser().resolve())
        config.backup_folders = [f for f in config.backup_folders if f != resolved]
    if args.add or args.remove:
        save_config(config, config_dir)
        print("Saved. Restart the background service to apply (`cloudsync install-service`).")
    for folder in config.backup_folders:
        print(folder)
    return EXIT_OK


def cmd_install_service(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    config = load_config(config_dir)
    if not _require_login(config):
        return EXIT_USAGE
    try:
        plan = service_module.service_plan(
            service_module.current_platform(),
            sys.executable,
            service_module.home_dir(),
            config_dir,
            frozen=bool(getattr(sys, "frozen", False)),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    if args.print_only:
        for path, text in plan.files.items():
            print(f"# {path}\n{text}")
        for command in plan.install_commands:
            print("$", " ".join(command))
        return EXIT_OK
    failed = service_module.install(plan)
    for line in failed:
        print(f"  failed: {line}", file=sys.stderr)
    if failed:
        return EXIT_ERRORS
    print(f"Installed {plan.description}. The client now starts when you log in.")
    return EXIT_OK


def cmd_uninstall_service(args: argparse.Namespace, config_dir: Path | None, http=None) -> int:
    try:
        plan = service_module.service_plan(
            service_module.current_platform(), sys.executable, service_module.home_dir(), config_dir
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    service_module.uninstall(plan)
    print("Removed the automatic start. Your files and backups were left untouched.")
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
    login.add_argument(
        "--folder",
        action="append",
        help="folder to keep in sync (default: ~/CloudSync); repeat it in backup mode",
    )
    login.add_argument("--otp", help="two-factor code or recovery code, if the account uses one")
    login.add_argument(
        "--mode", choices=["sync", "backup"], help="sync both ways (default) or upload-only backup"
    )
    login.add_argument("--device-name", help="backup mode: name of this computer on the server")
    login.set_defaults(func=cmd_login)

    sub.add_parser("sync", help="sync once and exit").set_defaults(func=cmd_sync)
    sub.add_parser("run", help="keep syncing until stopped").set_defaults(func=cmd_run)
    sub.add_parser("status", help="show what is pending").set_defaults(func=cmd_status)
    folders = sub.add_parser("folders", help="backup mode: list, add or remove backed-up folders")
    folders.add_argument("--add", action="append")
    folders.add_argument("--remove", action="append")
    folders.set_defaults(func=cmd_folders)
    install = sub.add_parser("install-service", help="start automatically when you log in")
    install.add_argument(
        "--print", dest="print_only", action="store_true", help="show what would be installed"
    )
    install.set_defaults(func=cmd_install_service)
    sub.add_parser("uninstall-service", help="stop starting automatically").set_defaults(
        func=cmd_uninstall_service
    )
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
