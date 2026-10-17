"""share links: upload-only "drop" permission and a download limit

Revision ID: 0014_add_drop_links
Revises: 0013_add_file_text
Create Date: 2026-10-18 00:00:00.000000

Existing links are unchanged: no download limit, same permission as before.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_add_drop_links"
down_revision = "0013_add_file_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shares", sa.Column("max_downloads", sa.Integer(), nullable=True))
    op.drop_constraint("ck_shares_permission", "shares", type_="check")
    op.create_check_constraint(
        "ck_shares_permission", "shares", "permission IN ('view', 'edit', 'drop')"
    )


def downgrade() -> None:
    op.execute("UPDATE shares SET permission = 'view' WHERE permission = 'drop'")
    op.drop_constraint("ck_shares_permission", "shares", type_="check")
    op.create_check_constraint("ck_shares_permission", "shares", "permission IN ('view', 'edit')")
    op.drop_column("shares", "max_downloads")
