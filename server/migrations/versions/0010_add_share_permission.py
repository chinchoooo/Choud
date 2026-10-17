"""add shares.permission (view / edit links)

Revision ID: 0010_add_share_permission
Revises: 0009_add_shares
Create Date: 2026-10-18 00:00:00.000000

Existing links keep working exactly as before: they become "view" links.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_add_share_permission"
down_revision = "0009_add_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shares",
        sa.Column("permission", sa.String(length=8), nullable=False, server_default="view"),
    )
    op.create_check_constraint("ck_shares_permission", "shares", "permission IN ('view', 'edit')")


def downgrade() -> None:
    op.drop_constraint("ck_shares_permission", "shares", type_="check")
    op.drop_column("shares", "permission")
