"""add login_events (the account's sign-in history)

Revision ID: 0015_add_login_events
Revises: 0014_add_drop_links
Create Date: 2026-10-18 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015_add_login_events"
down_revision = "0014_add_drop_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("new_device", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_login_events_user_id", "login_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_login_events_user_id", table_name="login_events")
    op.drop_table("login_events")
