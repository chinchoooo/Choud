#!/usr/bin/env bash
# Restore a backup produced by backup.sh.
#
# Usage: ./scripts/restore.sh backups/<timestamp> [--yes]
#
# This OVERWRITES the running database and object storage. The backup's
# checksums are verified first; a damaged backup is refused before anything is
# touched. The backend is stopped during the restore so nothing writes to the
# database or store halfway through.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi

backup_dir="${1:?Usage: $0 <backup-dir> [--yes]}"
[ -d "$backup_dir" ] || { echo "No such backup directory: $backup_dir" >&2; exit 1; }

POSTGRES_USER="${POSTGRES_USER:-cloud}"
POSTGRES_DB="${POSTGRES_DB:-personal_cloud}"
STORAGE_ROOT="${STORAGE_ROOT:-/data/cloud}"

echo "Verifying backup checksums..."
if [ -f "${backup_dir}/SHA256SUMS" ]; then
    ( cd "$backup_dir" && sha256sum -c SHA256SUMS ) || { echo "Backup is damaged - refusing to restore." >&2; exit 1; }
else
    echo "WARNING: no SHA256SUMS in this backup (made by an older backup.sh); cannot verify it." >&2
fi

if [ "${2:-}" != "--yes" ]; then
    read -r -p "This will overwrite the current database and storage. Continue? [y/N] " confirm
    [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || { echo "Aborted."; exit 1; }
fi

echo "Stopping the backend and proxy so nothing writes during the restore..."
docker compose stop reverse-proxy backend

echo "Restoring PostgreSQL database '${POSTGRES_DB}'..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c \
    "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    < "${backup_dir}/database.sql"

echo "Restoring object storage (${STORAGE_ROOT})..."
docker compose exec -T engine sh -c "find ${STORAGE_ROOT:?} -mindepth 1 -delete && tar -C ${STORAGE_ROOT} -xf -" \
    < "${backup_dir}/storage.tar"

echo "Starting the backend and proxy again..."
docker compose start backend reverse-proxy

echo "Restore complete. Check: scripts/healthcheck.sh"
