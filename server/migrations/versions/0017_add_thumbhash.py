"""add files.thumbhash (a tiny blurry placeholder shown while the real thumbnail loads)

Revision ID: 0017_add_thumbhash
Revises: 0016_add_instance_settings
Create Date: 2026-10-18 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0017_add_thumbhash"
down_revision = "0016_add_instance_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("thumbhash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "thumbhash")
