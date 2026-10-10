#!/usr/bin/env bash
# One-command deploy: preflight checks -> build -> start -> wait for healthy.
# Safe to re-run (it is also how you apply an update after `git pull`).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

[ -f .env ] || scripts/setup.sh
scripts/preflight.sh

echo
echo "Building and starting the stack (the first build compiles the C++ engine and takes a few minutes)..."
docker compose up -d --build --remove-orphans

set -a; . ./.env; set +a
url="http://localhost:${HTTP_PORT:-80}"

echo "Waiting for the API to report healthy at ${url}/api/health ..."
for _ in $(seq 1 90); do
    if curl -fsS "${url}/api/health" >/dev/null 2>&1; then
        echo
        curl -fsS "${url}/api/health"; echo
        echo
        echo "Up. Open:"
        echo "  this machine   : ${url}"
        if command -v tailscale >/dev/null 2>&1; then
            ts_ip="$(tailscale ip -4 2>/dev/null | head -1 || true)"
            if [ -n "$ts_ip" ]; then echo "  over Tailscale : http://${ts_ip}:${HTTP_PORT:-80}"; fi
        fi
        exit 0
    fi
    printf '.'
    sleep 2
done

echo
echo "The API did not become healthy within 3 minutes. Recent logs:" >&2
docker compose ps >&2
docker compose logs --tail=40 backend engine postgres >&2
echo "See docs/errors.md for known problems and fixes." >&2
exit 1
