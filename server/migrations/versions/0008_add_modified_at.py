"""add files.modified_at and uploads.modified_at

Revision ID: 0008_add_modified_at
Revises: 0007_raise_default_quota
Create Date: 2026-10-18 00:00:00.000000

The last-modified time the uploading device reports for a file (a phone photo's own date, a
synced file's mtime). It is what lists show as the file's date; `created_at`/`updated_at` stay
the server's own bookkeeping times.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_add_modified_at"
down_revision = "0007_raise_default_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("uploads", sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("uploads", "modified_at")
    op.drop_column("files", "modified_at")
