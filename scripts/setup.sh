#!/usr/bin/env bash
# Bootstrap a local development environment: create .env, verify Docker is
# available, and build the images.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example. Edit it before deploying to a real server."
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is not installed. See https://docs.docker.com/engine/install/" >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "docker compose (v2 plugin) is not available." >&2
    exit 1
fi

echo "Building images..."
docker compose build

echo "Setup complete. Run 'make docker-up' (or 'docker compose up') to start."
