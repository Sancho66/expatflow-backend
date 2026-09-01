"""POST /help/search-miss + GET /admin/help/search-misses — the journal
of help searches that found nothing (the corpus-improvement engine).

Covers: the round trip (POST → visible in the superadmin listing, newest
first), the superadmin gate (agency admin → 403), auth (no token → 401),
extra="forbid" and the 200-char cap, the per-agent burst guard, and the
response_model render pinned key by key."""

import pytest
from httpx import AsyncClient

from shared.models.agent import Agent
from shared.models.rbac import Role
from tests.plugins.agent_plugin import AuthHeaders, MakeAgent

pytestmark = pytest.mark.usefixtures("rbac_baseline")

_BODY = {"query": "comment exporter un dossier", "route": "/cases", "lang": "fr"}


@pytest.fixture
async def superadmin(make_agent: MakeAgent, system_roles: dict[str, Role]) -> Agent:
    return await make_agent(role=system_roles["superadmin"], email="root@platform.io")


async def test_post_then_visible_in_superadmin_listing_newest_first(
    client: AsyncClient,
    agent: Agent,
    superadmin: Agent,
    agent_headers: AuthHeaders,
) -> None:
    h = agent_headers(agent)
    first = await client.post("/help/search-miss", headers=h, json=_BODY)
    assert first.status_code == 201, first.text
    second = await client.post(
        "/help/search-miss", headers=h, json={**_BODY, "query": "relance whatsapp"}
    )
    assert second.status_code == 201

    listed = await client.get("/admin/help/search-misses", headers=agent_headers(superadmin))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 2 and body["page"] == 1
    queries = [item["query"] for item in body["items"]]
    assert queries == ["relance whatsapp", "comment exporter un dossier"]  # newest first
    assert body["items"][0]["agency_id"] == str(agent.agency_id)
    assert body["items"][0]["agent_id"] == str(agent.id)


async def test_listing_is_superadmin_only_and_post_needs_a_token(
    client: AsyncClient, agent: Agent, agent_headers: AuthHeaders
) -> None:
    # Agency admin (agent lambda for the platform): 403 on the read.
    denied = await client.get("/admin/help/search-misses", headers=agent_headers(agent))
    assert denied.status_code == 403, denied.text
    # No token on the POST: 401.
    anonymous = await client.post("/help/search-miss", json=_BODY)
    assert anonymous.status_code == 401


async def test_body_is_strict_and_query_is_capped(
    client: AsyncClient, agent: Agent, agent_headers: AuthHeaders
) -> None:
    h = agent_headers(agent)
    extra = await client.post("/help/search-miss", headers=h, json={**_BODY, "email": "x@y.z"})
    assert extra.status_code == 422  # extra="forbid" — no PII sneaks in
    too_long = await client.post("/help/search-miss", headers=h, json={**_BODY, "query": "q" * 201})
    assert too_long.status_code == 422


async def test_burst_guard_is_per_agent(
    client: AsyncClient,
    agent: Agent,
    make_agent: MakeAgent,
    system_roles: dict[str, Role],
    agent_headers: AuthHeaders,
) -> None:
    h = agent_headers(agent)
    for i in range(10):
        ok = await client.post("/help/search-miss", headers=h, json={**_BODY, "query": f"q{i}"})
        assert ok.status_code == 201, ok.text
    eleventh = await client.post("/help/search-miss", headers=h, json=_BODY)
    assert eleventh.status_code == 429
    assert eleventh.json()["code"] == "too_many_requests"
    # PER agent: a colleague's window is untouched.
    other = await make_agent(role=system_roles["member"], email="other@example.com")
    still_ok = await client.post("/help/search-miss", headers=agent_headers(other), json=_BODY)
    assert still_ok.status_code == 201


async def test_response_models_render_with_their_exact_keys(
    client: AsyncClient,
    agent: Agent,
    superadmin: Agent,
    agent_headers: AuthHeaders,
) -> None:
    created = await client.post("/help/search-miss", headers=agent_headers(agent), json=_BODY)
    posted = created.json()
    assert set(posted) == {"id", "agency_id", "agent_id", "query", "route", "lang", "created_at"}

    listed = (
        await client.get("/admin/help/search-misses", headers=agent_headers(superadmin))
    ).json()
    assert set(listed) == {"items", "total", "page", "page_size"}
    assert set(listed["items"][0]) == set(posted)
