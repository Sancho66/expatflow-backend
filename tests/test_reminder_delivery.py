"""Delivery proof (incident Bulgarie 01/09): the Resend message id is
persisted at send time, the signed Svix webhook writes delivery events on
the reminder, the contract serves the DERIVED status.

Covers the four required witnesses — send → id persisted; signed webhook →
status updated; invalid signature → 401 without a write; replay → a single
write — plus the never-500 doctrine (unknown event, unknown id, malformed
payload) and the rendered contract keys."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from shared.models.agent import Agent
from shared.models.client_case import ClientCase
from shared.models.rbac import Role
from shared.models.reminder import Reminder
from src.reminders.reminders_jobs import dispatch_due_reminders
from tests.plugins.agent_plugin import AuthHeaders, MakeAgent
from tests.plugins.case_plugin import MakeClientCase
from tests.plugins.expat_plugin import MakeExpatUser
from tests.plugins.reminder_plugin import MakeReminder

pytestmark = pytest.mark.usefixtures("rbac_baseline")

_SECRET = "whsec_" + base64.b64encode(b"delivery-proof-test-key").decode()
_PAST = datetime.now(UTC) - timedelta(hours=1)


@pytest_asyncio.fixture
async def admin_agent(make_agent: MakeAgent, system_roles: dict[str, Role]) -> Agent:
    return await make_agent(role=system_roles["admin"], email="boss@example.com")


@pytest_asyncio.fixture
async def martin_case(
    admin_agent: Agent, make_client_case: MakeClientCase, make_expat_user: MakeExpatUser
) -> ClientCase:
    principal = await make_expat_user(activated=True, email="martin-delivery@example.com")
    return await make_client_case(
        agency_id=admin_agent.agency_id,
        principal_expat_user_id=principal.id,
        owner_agent_id=admin_agent.id,
    )


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch: pytest.MonkeyPatch):
    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "resend_webhook_secret", _SECRET)


def _signed_headers(body: bytes, *, secret: str = _SECRET, timestamp: int | None = None) -> dict:
    svix_id = "msg_test"
    ts = str(timestamp if timestamp is not None else int(time.time()))
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{svix_id}.{ts}.".encode() + body
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {"svix-id": svix_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}"}


def _event(kind: str, email_id: str, *, occurred: str = "2026-09-01T10:00:00.000Z") -> bytes:
    payload: dict = {
        "type": f"email.{kind}",
        "created_at": occurred,
        "data": {"email_id": email_id, "to": ["x@example.com"], "subject": "s"},
    }
    if kind == "bounced":
        payload["data"]["bounce"] = {"message": "550 mailbox unavailable", "type": "Permanent"}
    return json.dumps(payload).encode()


async def _sent_reminder(
    db_session: AsyncSession,
    sync_session_local: sessionmaker[Session],
    case: ClientCase,
    make_reminder: MakeReminder,
) -> uuid.UUID:
    reminder = await make_reminder(case=case, status="approved", scheduled_at=_PAST)
    with sync_session_local() as db:
        stats = dispatch_due_reminders(db, log=lambda _line: None)
    assert stats["sent"] >= 1 and stats["emails"] >= 1
    return reminder.id


async def _row(db_session: AsyncSession, reminder_id: uuid.UUID) -> Reminder:
    db_session.expire_all()
    return (
        await db_session.execute(select(Reminder).where(Reminder.id == reminder_id))
    ).scalar_one()


async def test_send_persists_the_provider_message_id(
    db_session: AsyncSession,
    sync_session_local: sessionmaker[Session],
    martin_case: ClientCase,
    make_reminder: MakeReminder,
) -> None:
    rid = await _sent_reminder(db_session, sync_session_local, martin_case, make_reminder)
    row = await _row(db_session, rid)
    assert row.status == "sent"
    assert row.provider_message_id is not None and row.provider_message_id.startswith("mock-")
    assert row.delivery_status == "sent"  # derived: posted, no event yet


async def test_signed_webhook_updates_the_delivery_status(
    client: AsyncClient,
    db_session: AsyncSession,
    sync_session_local: sessionmaker[Session],
    martin_case: ClientCase,
    make_reminder: MakeReminder,
) -> None:
    rid = await _sent_reminder(db_session, sync_session_local, martin_case, make_reminder)
    mid = (await _row(db_session, rid)).provider_message_id
    body = _event("bounced", mid)
    resp = await client.post("/webhooks/resend", content=body, headers=_signed_headers(body))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "processed"}
    row = await _row(db_session, rid)
    assert row.delivery_status == "bounced"
    assert row.delivery_status_at == datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    assert "550 mailbox unavailable" in (row.delivery_reason or "")


async def test_invalid_signature_is_401_and_writes_nothing(
    client: AsyncClient,
    db_session: AsyncSession,
    sync_session_local: sessionmaker[Session],
    martin_case: ClientCase,
    make_reminder: MakeReminder,
) -> None:
    rid = await _sent_reminder(db_session, sync_session_local, martin_case, make_reminder)
    mid = (await _row(db_session, rid)).provider_message_id
    body = _event("delivered", mid)
    bad = _signed_headers(body, secret="whsec_" + base64.b64encode(b"wrong-key").decode())
    resp = await client.post("/webhooks/resend", content=body, headers=bad)
    assert resp.status_code == 401
    row = await _row(db_session, rid)
    assert row.delivery_event is None and row.delivery_status == "sent"
    # Stale timestamp: refused too (replay tolerance), same 401.
    old = _signed_headers(body, timestamp=int(time.time()) - 3600)
    assert (await client.post("/webhooks/resend", content=body, headers=old)).status_code == 401


async def test_replaying_the_same_event_writes_once(
    client: AsyncClient,
    db_session: AsyncSession,
    sync_session_local: sessionmaker[Session],
    martin_case: ClientCase,
    make_reminder: MakeReminder,
) -> None:
    rid = await _sent_reminder(db_session, sync_session_local, martin_case, make_reminder)
    mid = (await _row(db_session, rid)).provider_message_id
    body = _event("delivered", mid)
    first = await client.post("/webhooks/resend", content=body, headers=_signed_headers(body))
    assert first.json() == {"status": "processed"}
    stamp = (await _row(db_session, rid)).updated_at
    replay = await client.post("/webhooks/resend", content=body, headers=_signed_headers(body))
    assert replay.status_code == 200 and replay.json() == {"status": "duplicate"}
    row = await _row(db_session, rid)
    assert row.updated_at == stamp  # a single write — the replay touched nothing


async def test_without_configured_secret_the_webhook_refuses_everything(
    client: AsyncClient,
    db_session: AsyncSession,
    sync_session_local: sessionmaker[Session],
    martin_case: ClientCase,
    make_reminder: MakeReminder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No RESEND_WEBHOOK_SECRET on the env -> 401 for EVERY request, even
    one carrying a well-formed Svix signature: an unconfigured endpoint
    must never accept (there is nothing to verify against)."""
    from src.core.config import get_settings

    rid = await _sent_reminder(db_session, sync_session_local, martin_case, make_reminder)
    mid = (await _row(db_session, rid)).provider_message_id
    monkeypatch.setattr(get_settings(), "resend_webhook_secret", None)
    body = _event("delivered", mid)
    resp = await client.post("/webhooks/resend", content=body, headers=_signed_headers(body))
    assert resp.status_code == 401
    row = await _row(db_session, rid)
    assert row.delivery_event is None and row.delivery_status == "sent"  # nothing written


async def test_unknown_event_and_unknown_id_are_ignored_never_500(
    client: AsyncClient,
) -> None:
    body = _event("opened", "re_whatever")  # a type we don't track
    resp = await client.post("/webhooks/resend", content=body, headers=_signed_headers(body))
    assert resp.status_code == 200 and resp.json() == {"status": "ignored"}
    body = _event("delivered", "re_unknown_id")  # no reminder carries it
    resp = await client.post("/webhooks/resend", content=body, headers=_signed_headers(body))
    assert resp.status_code == 200 and resp.json() == {"status": "ignored"}
    malformed = b'{"type": "email.delivered"}'  # no created_at, no data
    resp = await client.post(
        "/webhooks/resend", content=malformed, headers=_signed_headers(malformed)
    )
    assert resp.status_code == 200 and resp.json() == {"status": "ignored"}


async def test_contract_serves_the_derived_delivery_fields(
    client: AsyncClient,
    db_session: AsyncSession,
    sync_session_local: sessionmaker[Session],
    martin_case: ClientCase,
    admin_agent: Agent,
    agent_headers: AuthHeaders,
    make_reminder: MakeReminder,
) -> None:
    headers = agent_headers(admin_agent)  # before _row: expire_all would expire the agent
    rid = await _sent_reminder(db_session, sync_session_local, martin_case, make_reminder)
    mid = (await _row(db_session, rid)).provider_message_id
    body = _event("complained", mid)
    await client.post("/webhooks/resend", content=body, headers=_signed_headers(body))
    payload = (await client.get(f"/reminders/{rid}", headers=headers)).json()
    assert payload["delivery_status"] == "complained"
    assert payload["delivery_status_at"] is not None
    for key in ("delivery_status", "delivery_status_at", "delivery_reason"):
        assert key in payload
