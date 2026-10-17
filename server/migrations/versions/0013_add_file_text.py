"""add file_text (searchable text of file contents)

Revision ID: 0013_add_file_text
Revises: 0012_add_two_factor
Create Date: 2026-10-18 00:00:00.000000

Derived data: safe to drop and rebuild. On PostgreSQL the text gets a full-text (GIN) index.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_add_file_text"
down_revision = "0012_add_two_factor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_text",
        sa.Column(
            "file_id",
            sa.Uuid(),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_file_text_fts ON file_text USING gin (to_tsvector('simple', text))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_file_text_fts")
    op.drop_table("file_text")
