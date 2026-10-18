"""raise existing users' storage quota to 400 GiB

Revision ID: 0007_raise_default_quota
Revises: 0006_add_library_features
Create Date: 2026-10-18 00:00:00.000000

The default quota used to be 10 GiB. This is a personal server whose disk is meant to be used,
so every account below 400 GiB is raised to it. Accounts someone deliberately set higher are
left alone, and the downgrade does not shrink anyone's quota (that could lock people out of
data they already stored).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_raise_default_quota"
down_revision = "0006_add_library_features"
branch_labels = None
depends_on = None

QUOTA_BYTES = 400 * 1024**3


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE users SET storage_quota = :quota WHERE storage_quota < :quota").bindparams(
            quota=QUOTA_BYTES
        )
    )


def downgrade() -> None:
    # Deliberately a no-op: the old per-account values were not recorded, and lowering a quota
    # below what a person already stores would only break their uploads. Nothing else to undo.
    return None
