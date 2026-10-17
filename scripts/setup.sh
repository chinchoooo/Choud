#!/usr/bin/env bash
# Create .env with strong, random secrets. Never overwrites an existing .env.
#
#   scripts/setup.sh           create .env if it does not exist
#   scripts/setup.sh --build   ...and also build the images
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

random_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        python3 -c 'import secrets; print(secrets.token_hex(32))'
    fi
}

if [ -f .env ]; then
    echo ".env already exists - leaving it untouched."
else
    # Copy .env.example line by line, replacing only the two secrets.
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            JWT_SECRET=*)        echo "JWT_SECRET=$(random_secret)" ;;
            POSTGRES_PASSWORD=*) echo "POSTGRES_PASSWORD=$(random_secret)" ;;
            *)                   printf '%s\n' "$line" ;;
        esac
    done < .env.example > .env
    chmod 600 .env
    echo "Created .env with freshly generated secrets (mode 600)."
    echo "Back this file up somewhere safe: losing JWT_SECRET logs everyone out,"
    echo "losing POSTGRES_PASSWORD makes the existing database unreadable."
fi

if [ "${1:-}" = "--build" ]; then
    command -v docker >/dev/null 2>&1 || { echo "docker is not installed. See https://docs.docker.com/engine/install/" >&2; exit 1; }
    docker compose version >/dev/null 2>&1 || { echo "docker compose (v2 plugin) is not available." >&2; exit 1; }
    echo "Building images..."
    docker compose build
fi

echo "Next: scripts/deploy.sh  (checks everything, then starts the stack)"
