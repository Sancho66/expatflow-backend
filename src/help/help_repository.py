import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.help_search_miss import HelpSearchMiss


class HelpRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_miss(
        self, *, agency_id: uuid.UUID, agent_id: uuid.UUID, query: str, route: str, lang: str
    ) -> HelpSearchMiss:
        miss = HelpSearchMiss(
            agency_id=agency_id, agent_id=agent_id, query=query, route=route, lang=lang
        )
        self.db.add(miss)
        await self.db.flush()
        await self.db.refresh(miss)
        return miss

    async def list_misses(self, *, page: int, page_size: int) -> tuple[list[HelpSearchMiss], int]:
        """Platform-wide, newest first — deliberately CROSS-agency: this is
        the superadmin corpus-improvement read, gated by the platform
        permission at the binding."""
        total = (await self.db.execute(select(func.count(HelpSearchMiss.id)))).scalar_one()
        rows = (
            await self.db.execute(
                select(HelpSearchMiss)
                .order_by(HelpSearchMiss.created_at.desc(), HelpSearchMiss.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
        return list(rows), total
