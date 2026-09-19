#!/usr/bin/env bash
# Check backend API health (which in turn verifies the database, the C++
# engine, and storage). Exits non-zero if unhealthy.
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:${BACKEND_PORT:-8000}}"

response="$(curl -fsS "${BACKEND_URL}/api/health")" || {
    echo "Backend API is unreachable at ${BACKEND_URL}" >&2
    exit 1
}

echo "$response"

status="$(echo "$response" | grep -o '"status":"[a-z]*"' | cut -d'"' -f4)"
if [ "$status" != "healthy" ]; then
    exit 1
fi
