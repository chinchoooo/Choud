#!/usr/bin/env bash
# Check API health through the reverse proxy (which in turn reports on the
# database, the C++ engine, and storage). Exits non-zero if unhealthy.
#
# Used by the optional monitoring timer in deployment/systemd/ and handy by
# hand:  scripts/healthcheck.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi

BASE_URL="${BASE_URL:-http://localhost:${HTTP_PORT:-80}}"

response="$(curl -fsS --max-time 10 "${BASE_URL}/api/health")" || {
    echo "API is unreachable or unhealthy at ${BASE_URL}" >&2
    exit 1
}

echo "$response"

if ! echo "$response" | grep -q '"status":"healthy"'; then
    exit 1
fi
