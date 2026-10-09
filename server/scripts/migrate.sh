#!/usr/bin/env bash
# Apply database migrations. Safe to run repeatedly (idempotent).
#
# Runs automatically every time the backend container starts (see
# ../entrypoint.sh), and can be run by hand with `make migrate` /
# `make docker-migrate`.
#
# Pre-creates Alembic's own internal "alembic_version" tracking table
# with a wide-enough version_num column *before* Alembic gets a chance
# to create its default (32-char) one. This project's migration revision
# names are longer, descriptive strings (e.g.
# "0002_add_folders_and_files_tables") rather than short hash IDs, and
# they overflow Alembic's built-in default column width, causing
# "StringDataRightTruncation" partway through "alembic upgrade head".
# See docs/errors.md.
set -euo pipefail

# Always run from the server/ root (/app in the container), where
# alembic.ini and the `app` package live, whatever the caller's cwd is.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

python -c "
from app.core.database import engine
from sqlalchemy import text

with engine.begin() as conn:
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(255) NOT NULL,
            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        )
    '''))
"

alembic upgrade head
