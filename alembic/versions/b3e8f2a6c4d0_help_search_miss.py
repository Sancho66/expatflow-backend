"""help search-miss journal

Searches of the help corpus that returned nothing, reported by agents —
the corpus-improvement engine. Additive, no backfill; no PII beyond the
query text. `agent_id` SET NULL: the miss outlives its author.

Revision ID: b3e8f2a6c4d0
Revises: z2c7d4e0f6a8
"""

import sqlalchemy as sa
from alembic import op

revision = "b3e8f2a6c4d0"
down_revision = "z2c7d4e0f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "help_search_miss",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("route", sa.String(length=200), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agency.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Deny-all RLS posture, like every other table.
    op.execute("ALTER TABLE help_search_miss ENABLE ROW LEVEL SECURITY")
    op.create_index(
        "ix_help_search_miss_agency_id", "help_search_miss", ["agency_id"], unique=False
    )
    op.create_index(
        "ix_help_search_miss_created_at", "help_search_miss", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_help_search_miss_created_at", table_name="help_search_miss")
    op.drop_index("ix_help_search_miss_agency_id", table_name="help_search_miss")
    op.drop_table("help_search_miss")
