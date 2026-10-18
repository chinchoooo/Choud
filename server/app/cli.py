"""Maintenance commands, run inside the backend container:

    docker compose exec backend python -m app.cli gc              # report only
    docker compose exec backend python -m app.cli gc --delete     # actually remove orphans
    docker compose exec backend python -m app.cli index [--all]   # (re)build the search index
    docker compose exec backend python -m app.cli fix-dates [--apply]  # undated photos

(`scripts/gc.sh` wraps this.) Exit code 0 on success, 1 if anything could not be done.
"""

import argparse
import json
import sys
from pathlib import Path

from app.core import database
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services import dates_service, gc_service, index_service
from app.services.storage_service import get_storage_service


def _gc(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = database.SessionLocal()
    try:
        report = gc_service.run_gc(
            db,
            get_storage_service(),
            Path(settings.storage_root),
            delete=args.delete,
            grace_hours=args.grace_hours
            if args.grace_hours is not None
            else settings.gc_grace_hours,
        )
    finally:
        db.close()
    print(report.summary())
    if args.json:
        print(json.dumps(report.__dict__, default=str, indent=2))
    return 1 if report.errors else 0


def _index(args: argparse.Namespace) -> int:
    db = database.SessionLocal()
    try:
        if args.all:
            index_service.reset_index(db)
        totals = {"ok": 0, "skipped": 0, "failed": 0}
        while True:
            counts = index_service.index_pending(db, args.batch)
            for key, value in counts.items():
                totals[key] += value
            if not any(counts.values()):
                break
            print(f"indexed so far: {totals}", flush=True)
    finally:
        db.close()
    print(f"done: {totals}")
    return 0


def _fix_dates(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.models.user import User

    db = database.SessionLocal()
    try:
        total = 0
        for user in db.execute(select(User)).scalars():
            report = dates_service.fix_dates(db, user, dry_run=not args.apply)
            total += report.fixed
            print(
                f"{user.email}: {report.checked} undated, {report.from_name} from names, "
                f"{report.from_exif} from EXIF, {report.no_date_found} with no date found"
            )
            for line in report.examples:
                print("   ", line)
    finally:
        db.close()
    note = "applied" if args.apply else "preview only: nothing was changed (add --apply)"
    print(note, f"({total})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gc = sub.add_parser("gc", help="find (and optionally remove) storage nothing references")
    gc.add_argument(
        "--delete", action="store_true", help="remove what is found (default: report only)"
    )
    gc.add_argument(
        "--grace-hours", type=float, default=None, help="leave anything newer than this"
    )
    gc.add_argument("--json", action="store_true", help="also print the full report as JSON")
    gc.set_defaults(func=_gc)
    index = sub.add_parser(
        "index", help="extract the text of files so their contents are searchable"
    )
    index.add_argument("--all", action="store_true", help="throw the index away and rebuild it")
    index.add_argument("--batch", type=int, default=100)
    index.set_defaults(func=_index)
    fix = sub.add_parser("fix-dates", help="give undated photos and videos their real date")
    fix.add_argument("--apply", action="store_true", help="change the dates (default: preview)")
    fix.set_defaults(func=_fix_dates)
    args = parser.parse_args(argv)
    configure_logging(get_settings().backend_log_level)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
