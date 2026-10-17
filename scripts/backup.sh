#!/usr/bin/env bash
# Back up PostgreSQL metadata and the object storage volume into
# backups/<timestamp>/. Requires the stack to be running.
#
# What a backup contains (BOTH are needed - objects without the database are
# anonymous blobs, and the database without objects points at nothing):
#   database.sql   pg_dump of the whole database
#   storage.tar    the object store + chunk area
#   .env           the secrets the stack was running with
#   SHA256SUMS     checksums, verified by restore.sh
#
# Environment (all optional, usually set in .env):
#   BACKUP_KEEP     how many backups to keep (default 14); older ones are deleted
#   BACKUP_COPY_TO  also copy the new backup to this directory, e.g. a mounted
#                   external drive or a network share. A backup that lives only
#                   on the same disk as the data is not a backup.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
# shellcheck source=lib/notify.sh
. scripts/lib/notify.sh

# Any failure below (set -e, or an explicit "backup FAILED") ends up here and raises an alert
# (when ALERT_WEBHOOK_URL is set; see scripts/lib/notify.sh).
trap 'rc=$?; if [ "$rc" -ne 0 ]; then notify_event backup fail "Choud backup FAILED" "scripts/backup.sh exited with code $rc on $(hostname)"; fi' EXIT

POSTGRES_USER="${POSTGRES_USER:-cloud}"
POSTGRES_DB="${POSTGRES_DB:-personal_cloud}"
STORAGE_ROOT="${STORAGE_ROOT:-/data/cloud}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="backups/${timestamp}"
tmp_dir="backups/.incomplete-${timestamp}"
mkdir -p "$tmp_dir"
trap 'rm -rf "$tmp_dir"' ERR

echo "Dumping PostgreSQL database '${POSTGRES_DB}'..."
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "${tmp_dir}/database.sql"

echo "Archiving object storage (${STORAGE_ROOT})..."
docker compose exec -T engine tar -C "$STORAGE_ROOT" -cf - . > "${tmp_dir}/storage.tar"

if [ -f .env ]; then
    cp .env "${tmp_dir}/.env"
    chmod 600 "${tmp_dir}/.env"
fi

# --- verify before declaring success -----------------------------------------
[ -s "${tmp_dir}/database.sql" ] || { echo "database.sql is empty - backup FAILED" >&2; exit 1; }
grep -q "PostgreSQL database dump complete" "${tmp_dir}/database.sql" \
    || { echo "database.sql looks truncated - backup FAILED" >&2; exit 1; }
tar -tf "${tmp_dir}/storage.tar" >/dev/null \
    || { echo "storage.tar is not a readable archive - backup FAILED" >&2; exit 1; }

( cd "$tmp_dir" && sha256sum database.sql storage.tar > SHA256SUMS )

# Only a complete, verified backup ever gets a real name.
mv "$tmp_dir" "$out_dir"
trap - ERR
echo "Backup written to ${out_dir} ($(du -sh "$out_dir" | cut -f1))"
notify_event backup ok "Choud backup" "Backup ${timestamp} written ($(du -sh "$out_dir" | cut -f1))"

# --- off-site / second copy ---------------------------------------------------
if [ -n "${BACKUP_COPY_TO:-}" ]; then
    if [ -d "$BACKUP_COPY_TO" ]; then
        cp -r "$out_dir" "${BACKUP_COPY_TO}/"
        echo "Copied to ${BACKUP_COPY_TO}/${timestamp}"
        notify_event backup-copy ok "Choud backup copy" "Second copy written to ${BACKUP_COPY_TO}"
    else
        echo "WARNING: BACKUP_COPY_TO='${BACKUP_COPY_TO}' is not a directory (drive not mounted?) - no second copy made" >&2
        notify_event backup-copy fail "Choud backup has no second copy" "BACKUP_COPY_TO=${BACKUP_COPY_TO} is not a directory (drive not mounted?). The backup only exists on this machine."
    fi
else
    echo "NOTE: BACKUP_COPY_TO is not set - this backup only exists on this machine."
fi

# --- retention ---------------------------------------------------------------
# Newest first; delete everything after the first BACKUP_KEEP.
# shellcheck disable=SC2012
ls -1d backups/2* 2>/dev/null | sort -r | tail -n +"$((BACKUP_KEEP + 1))" | while read -r old; do
    echo "Removing old backup ${old}"
    rm -rf "$old"
done
