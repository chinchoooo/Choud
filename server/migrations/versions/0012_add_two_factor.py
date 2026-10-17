"""add two-factor login (TOTP) columns and recovery codes

Revision ID: 0012_add_two_factor
Revises: 0011_add_invites
Create Date: 2026-10-18 00:00:00.000000

Existing accounts keep working exactly as before: two-factor is off until the owner turns it on.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_add_two_factor"
down_revision = "0011_add_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.add_column(
        "users", sa.Column("totp_failures", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "users", sa.Column("totp_locked_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_recovery_codes_user_id", "recovery_codes", ["user_id"])
    op.create_index("ix_recovery_codes_code_hash", "recovery_codes", ["code_hash"])


def downgrade() -> None:
    op.drop_index("ix_recovery_codes_code_hash", table_name="recovery_codes")
    op.drop_index("ix_recovery_codes_user_id", table_name="recovery_codes")
    op.drop_table("recovery_codes")
    for column in (
        "totp_locked_until",
        "totp_failures",
        "totp_last_step",
        "totp_enabled",
        "totp_secret",
    ):
        op.drop_column("users", column)
