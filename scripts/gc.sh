#!/usr/bin/env bash
# Finds storage nothing references (orphaned objects, stale thumbnails and staging files,
# abandoned upload folders). By default it only REPORTS; nothing is removed unless you pass --delete.
#
#   scripts/gc.sh                       # what would be removed
#   scripts/gc.sh --delete              # remove it (objects younger than 72 h are always kept)
#   scripts/gc.sh --delete --grace-hours 168
#
# The backend also reports this once a day on its own; set GC_DELETE_ENABLED=true in .env to let
# that daily pass delete as well. See app/services/gc_service.py for the safety rules.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec docker compose exec -T backend python -m app.cli gc "$@"
