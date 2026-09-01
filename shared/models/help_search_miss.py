import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, UUIDPrimaryKeyMixin


class HelpSearchMiss(UUIDPrimaryKeyMixin, Base):
    """Help searches that returned NOTHING — the corpus-improvement
    journal. Immutable (`created_at` only, no TimestampMixin), no PII
    beyond the query text itself. `agent_id` is SET NULL on agent
    deletion: the miss outlives its author, the corpus gap remains."""

    __tablename__ = "help_search_miss"
    __table_args__ = (
        # The superadmin listing reads newest-first, platform-wide.
        Index("ix_help_search_miss_created_at", "created_at"),
    )

    agency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agency.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent.id", ondelete="SET NULL"), nullable=True
    )
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    route: Mapped[str] = mapped_column(String(200), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
