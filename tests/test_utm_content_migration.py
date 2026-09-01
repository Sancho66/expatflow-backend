"""Migration proof for d5a1b7c3e9f2 (utm_content, landing-button
attribution): one additive nullable column on BOTH acquisition tables,
clean roundtrip, the four neighbour fields untouched, the existing park
honestly NULL — the acquisition-migration doctrine, verbatim."""

import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

from alembic import command

PARENT = "c4f9a2e6b8d1"
THIS = "d5a1b7c3e9f2"

NEIGHBOURS = ("utm_source", "utm_medium", "utm_campaign", "referrer")


@pytest.fixture(scope="module")
def alembic_db():
    from src.core.config import get_settings

    saved = os.environ.get("DATABASE_URL_SYNC")
    with PostgresContainer("postgres:16-alpine") as pg:
        os.environ["DATABASE_URL_SYNC"] = pg.get_connection_url()
        get_settings.cache_clear()
        cfg = Config("alembic.ini")
        engine = create_engine(pg.get_connection_url())
        try:
            yield cfg, engine
        finally:
            engine.dispose()
            if saved is None:
                os.environ.pop("DATABASE_URL_SYNC", None)
            else:
                os.environ["DATABASE_URL_SYNC"] = saved
            get_settings.cache_clear()


def _cols(engine, table: str) -> set[str]:
    with engine.begin() as c:
        return {
            r[0]
            for r in c.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": table},
            )
        }


def test_utm_content_roundtrip(alembic_db) -> None:
    cfg, engine = alembic_db
    command.upgrade(cfg, PARENT)
    assert "utm_content" not in _cols(engine, "agency")
    assert "utm_content" not in _cols(engine, "signup_verification")

    command.upgrade(cfg, THIS)
    assert "utm_content" in _cols(engine, "agency")
    assert "utm_content" in _cols(engine, "signup_verification")
    # The four neighbours are intact: utm_content lands BESIDE them.
    assert set(NEIGHBOURS) <= _cols(engine, "agency")

    command.downgrade(cfg, PARENT)
    assert "utm_content" not in _cols(engine, "agency")
    assert "utm_content" not in _cols(engine, "signup_verification")
    assert set(NEIGHBOURS) <= _cols(engine, "agency")

    command.upgrade(cfg, THIS)
    assert "utm_content" in _cols(engine, "agency")


def test_the_existing_park_stays_null(alembic_db) -> None:
    """An agency created BEFORE the lot has no button attribution, ever."""
    cfg, engine = alembic_db
    command.upgrade(cfg, THIS)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO agency (id, name, slug, settings, created_at, updated_at)"
                " VALUES (gen_random_uuid(), 'Ancienne', 'ancienne-content', '{}'::jsonb,"
                " now(), now())"
            )
        )
        row = c.execute(
            text("SELECT utm_content FROM agency WHERE slug = 'ancienne-content'")
        ).one()
    assert row[0] is None
