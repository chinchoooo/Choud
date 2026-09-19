#!/usr/bin/env bash
# Restore a backup produced by backup.sh.
#
# Usage: ./scripts/restore.sh backups/<timestamp>
#
# This overwrites the running database and object storage — confirm before
# running against a server with data you care about.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -f .env ] && set -a && source .env && set +a

backup_dir="${1:?Usage: $0 <backup-dir>}"
[ -d "$backup_dir" ] || { echo "No such backup directory: $backup_dir" >&2; exit 1; }

POSTGRES_USER="${POSTGRES_USER:-cloud}"
POSTGRES_DB="${POSTGRES_DB:-personal_cloud}"
STORAGE_ROOT="${STORAGE_ROOT:-/data/cloud}"

read -r -p "This will overwrite the current database and storage. Continue? [y/N] " confirm
[ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || { echo "Aborted."; exit 1; }

echo "Restoring PostgreSQL database '${POSTGRES_DB}'..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "${backup_dir}/database.sql"

echo "Restoring object storage (${STORAGE_ROOT})..."
docker compose exec -T engine sh -c "rm -rf ${STORAGE_ROOT:?}/* && tar -C ${STORAGE_ROOT} -xf -" < "${backup_dir}/storage.tar"

echo "Restore complete."
