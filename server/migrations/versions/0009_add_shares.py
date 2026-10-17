"""add shares (public links, Phase 12)

Revision ID: 0009_add_shares
Revises: 0008_add_modified_at
Create Date: 2026-10-18 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_add_shares"
down_revision = "0008_add_modified_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shares",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "file_id", sa.Uuid(), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "folder_id", sa.Uuid(), sa.ForeignKey("folders.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(file_id IS NOT NULL AND folder_id IS NULL) "
            "OR (file_id IS NULL AND folder_id IS NOT NULL)",
            name="ck_shares_one_target",
        ),
    )
    op.create_index("ix_shares_owner_id", "shares", ["owner_id"])
    op.create_index("ix_shares_file_id", "shares", ["file_id"])
    op.create_index("ix_shares_folder_id", "shares", ["folder_id"])
    op.create_index("ix_shares_token", "shares", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_shares_token", table_name="shares")
    op.drop_index("ix_shares_folder_id", table_name="shares")
    op.drop_index("ix_shares_file_id", table_name="shares")
    op.drop_index("ix_shares_owner_id", table_name="shares")
    op.drop_table("shares")
