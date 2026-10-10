"""add uploads.base_version_id

Revision ID: 0005_add_upload_base_version
Revises: 0004_add_file_versions_table
Create Date: 2026-10-17 00:00:00.000000

Lets a chunked upload carry the same compare-and-swap precondition as a plain
upload (the version the client started from, or "none" for create-only), so a
sync client can detect that someone else changed the file while it was
uploading.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_add_upload_base_version"
down_revision = "0004_add_file_versions_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("base_version_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column("uploads", "base_version_id")
