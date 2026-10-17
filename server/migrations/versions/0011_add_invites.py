"""add invites (single-use registration codes)

Revision ID: 0011_add_invites
Revises: 0010_add_share_permission
Create Date: 2026-10-18 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_add_invites"
down_revision = "0010_add_share_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("storage_quota", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_invites_code", "invites", ["code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_invites_code", table_name="invites")
    op.drop_table("invites")
