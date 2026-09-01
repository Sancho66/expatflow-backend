"""Help search-miss journal: agents report searches that returned
nothing; the superadmin reads them — the corpus-improvement engine."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.agent import Agent
from src.core.dependencies import get_current_agent, get_db
from src.core.enums import Audience
from src.core.rbac.baseline import RouteBinding
from src.core.rbac.permissions import Permission
from src.help.help_manager import HelpManager
from src.help.help_schema import (
    HelpSearchMissCreate,
    HelpSearchMissListResponse,
    HelpSearchMissRead,
)

router = APIRouter(tags=["help"])

BINDINGS = [
    # Any authenticated agent may report a miss (permission None — the
    # /me idiom): searching the help in vain is not a guarded capability.
    RouteBinding("POST", "/help/search-miss", Audience.AGENT),
    # Platform read, cross-agency by design: same superadmin gate as the
    # rest of the platform admin surface (agency.create).
    RouteBinding("GET", "/admin/help/search-misses", Audience.AGENT, Permission.AGENCY_CREATE),
]

DbDep = Annotated[AsyncSession, Depends(get_db)]
AgentDep = Annotated[Agent, Depends(get_current_agent)]


@router.post("/help/search-miss", response_model=HelpSearchMissRead, status_code=201)
async def report_search_miss(
    payload: HelpSearchMissCreate, agent: AgentDep, db: DbDep
) -> HelpSearchMissRead:
    return await HelpManager(db).record_miss(agent, payload)


@router.get("/admin/help/search-misses", response_model=HelpSearchMissListResponse)
async def list_search_misses(
    agent: AgentDep,
    db: DbDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> HelpSearchMissListResponse:
    return await HelpManager(db).list_misses(page=page, page_size=page_size)
