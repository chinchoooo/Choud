"""add taken_at, favorites and activity (Phase 11)

Revision ID: 0006_add_library_features
Revises: 0005_add_upload_base_version
Create Date: 2026-10-17 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_add_library_features"
down_revision = "0005_add_upload_base_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("uploads", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "favorites",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column(
            "file_id", sa.Uuid(), sa.ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "activity",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_activity_user_id", "activity", ["user_id"])
    op.create_index("ix_activity_created_at", "activity", ["created_at"])
    op.create_index("ix_files_taken_at", "files", ["taken_at"])


def downgrade() -> None:
    op.drop_index("ix_files_taken_at", table_name="files")
    op.drop_index("ix_activity_created_at", table_name="activity")
    op.drop_index("ix_activity_user_id", table_name="activity")
    op.drop_table("activity")
    op.drop_table("favorites")
    op.drop_column("uploads", "taken_at")
    op.drop_column("files", "taken_at")
