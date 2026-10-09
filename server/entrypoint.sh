#!/usr/bin/env bash
# Container entrypoint for the backend: bring the database schema up to date,
# then hand over to the real command (uvicorn by default). Doing this here
# means a fresh `docker compose up` works with no manual migration step, and
# an upgrade that ships a new migration applies it on restart.
#
# If migrations fail, the container exits non-zero instead of serving an API
# that doesn't match its schema (Rule 5: never run on a half-migrated database).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "entrypoint: applying database migrations..."
bash scripts/migrate.sh

echo "entrypoint: starting: $*"
exec "$@"
