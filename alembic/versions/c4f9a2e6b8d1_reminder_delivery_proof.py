"""reminder delivery proof (incident Bulgarie 01/09)

The Resend message id at send time + the last delivery event from the
signed webhook (event, timestamp, raw reason). Additive, no backfill:
reminders sent before this lot simply have no proof — honest NULL.

ORDER CONSTRAINT: chains on b3e8f2a6c4d0 (help_search_miss, still
uncommitted at write time) — that lot must land first or together.

Revision ID: c4f9a2e6b8d1
Revises: b3e8f2a6c4d0
"""

import sqlalchemy as sa
from alembic import op

revision = "c4f9a2e6b8d1"
down_revision = "b3e8f2a6c4d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reminder", sa.Column("provider_message_id", sa.String(length=64), nullable=True))
    op.add_column("reminder", sa.Column("delivery_event", sa.String(length=20), nullable=True))
    op.add_column(
        "reminder", sa.Column("delivery_status_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("reminder", sa.Column("delivery_reason", sa.Text(), nullable=True))
    # The webhook resolves reminders by message id — the only read path.
    op.create_index(
        "ix_reminder_provider_message_id", "reminder", ["provider_message_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_reminder_provider_message_id", table_name="reminder")
    op.drop_column("reminder", "delivery_reason")
    op.drop_column("reminder", "delivery_status_at")
    op.drop_column("reminder", "delivery_event")
    op.drop_column("reminder", "provider_message_id")
