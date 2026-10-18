"""add instance_settings (server-wide switches such as the public-links kill switch)

Revision ID: 0016_add_instance_settings
Revises: 0015_add_login_events
Create Date: 2026-10-18 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_add_instance_settings"
down_revision = "0015_add_login_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instance_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("instance_settings")
