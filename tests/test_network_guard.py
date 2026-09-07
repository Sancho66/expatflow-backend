"""Prove that swallowed exceptions and pre-fixture calls cannot produce green CI."""

import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.parametrize(
    "scenario",
    [
        "caught",
        "collect",
        "fixture",
        "dns",
        "udp",
        "libpq",
        "subprocess",
        "httpx",
        "ipv6",
        "unix",
        "getnameinfo",
    ],
)
def test_forbidden_attempt_fails_child_session(scenario: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tests.network_guard_probe", scenario],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Network guard: 1 unmocked attempts" in result.stdout


def test_mock_transport_never_reaches_network() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tests.network_guard_probe", "mock"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Network guard: 0 unmocked attempts" in result.stdout


async def test_owned_postgres_is_reachable(db_session: AsyncSession) -> None:
    assert await db_session.scalar(text("SELECT 1")) == 1
