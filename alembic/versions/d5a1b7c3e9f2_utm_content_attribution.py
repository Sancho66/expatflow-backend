"""utm_content: landing-button attribution

Fifth acquisition field, same rail as the other four (columns on both the
verification transit table and the agency, 200-capped, first-touch wins).
Additive, no backfill: the source is perishable and cannot be
reconstructed — the existing fleet stays honestly NULL.

Revision ID: d5a1b7c3e9f2
Revises: c4f9a2e6b8d1
"""

import sqlalchemy as sa
from alembic import op

revision = "d5a1b7c3e9f2"
down_revision = "c4f9a2e6b8d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signup_verification", sa.Column("utm_content", sa.String(length=200), nullable=True))
    op.add_column("agency", sa.Column("utm_content", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("agency", "utm_content")
    op.drop_column("signup_verification", "utm_content")
