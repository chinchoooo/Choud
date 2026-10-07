"""add file_versions table

Revision ID: 0004_add_file_versions_table
Revises: 0003_add_uploads_table
Create Date: 2026-10-17 00:00:00.000000

Also backfills one version (number 1) for every file that already exists, so
rows created before this migration look exactly like rows created after it:
`files.current_version_id` is always set and always points at the newest
version. `files.current_version_id` deliberately has no foreign-key
constraint (files <-> file_versions would be a circular FK; the application
keeps the pointer consistent instead).
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_add_file_versions_table"
down_revision = "0003_add_uploads_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("restored_from_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("file_id", "version_number", name="uq_file_versions_file_id_number"),
    )
    op.create_index("ix_file_versions_file_id", "file_versions", ["file_id"])
    op.create_index("ix_file_versions_content_hash", "file_versions", ["content_hash"])

    # Backfill: give every existing file a version 1 and point it at it.
    bind = op.get_bind()
    files = bind.execute(
        sa.text(
            "SELECT id, owner_id, content_hash, size, created_at FROM files "
            "WHERE content_hash IS NOT NULL"
        )
    ).fetchall()
    for file_id, owner_id, content_hash, size, created_at in files:
        version_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO file_versions "
                "(id, file_id, version_number, content_hash, size, created_by, created_at) "
                "VALUES (:id, :file_id, 1, :content_hash, :size, :created_by, :created_at)"
            ),
            {
                "id": version_id,
                "file_id": file_id,
                "content_hash": content_hash,
                "size": size,
                "created_by": owner_id,
                "created_at": created_at,
            },
        )
        bind.execute(
            sa.text("UPDATE files SET current_version_id = :vid WHERE id = :fid"),
            {"vid": version_id, "fid": file_id},
        )


def downgrade() -> None:
    op.execute("UPDATE files SET current_version_id = NULL")
    op.drop_index("ix_file_versions_content_hash", table_name="file_versions")
    op.drop_index("ix_file_versions_file_id", table_name="file_versions")
    op.drop_table("file_versions")
