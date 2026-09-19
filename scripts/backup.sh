#!/usr/bin/env bash
# Back up PostgreSQL metadata and the object storage volume into
# backups/<timestamp>/. Requires the stack to be running (`docker compose up`).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -f .env ] && set -a && source .env && set +a

POSTGRES_USER="${POSTGRES_USER:-cloud}"
POSTGRES_DB="${POSTGRES_DB:-personal_cloud}"
STORAGE_ROOT="${STORAGE_ROOT:-/data/cloud}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="backups/${timestamp}"
mkdir -p "$out_dir"

echo "Dumping PostgreSQL database '${POSTGRES_DB}'..."
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "${out_dir}/database.sql"

echo "Archiving object storage (${STORAGE_ROOT})..."
docker compose exec -T engine tar -C "$STORAGE_ROOT" -cf - . > "${out_dir}/storage.tar"

if [ -f .env ]; then
    cp .env "${out_dir}/.env"
fi

echo "Backup written to ${out_dir}"
