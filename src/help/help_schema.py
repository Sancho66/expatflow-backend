import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HelpSearchMissCreate(BaseModel):
    """An agent searched the help corpus and got NOTHING. No PII beyond
    the query text; the actor/tenant come from the token, never the body."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    route: str = Field(min_length=1, max_length=200)
    lang: str = Field(min_length=2, max_length=8)


class HelpSearchMissRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agency_id: uuid.UUID
    agent_id: uuid.UUID | None
    query: str
    route: str
    lang: str
    created_at: datetime


class HelpSearchMissListResponse(BaseModel):
    items: list[HelpSearchMissRead]
    total: int
    page: int
    page_size: int
