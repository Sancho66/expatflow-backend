"""Fail closed before pytest collection; only owned local PostgreSQL is reachable."""

from __future__ import annotations

import os
import platform
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# Loaded via addopts, before conftest, application imports and test collection.
_VIOLATIONS: list[str] = []
_PORTS: set[int] = set()
_STARTING: ContextVar[bool] = ContextVar("starting_test_postgres", default=False)
_OWNED: dict[str, int] = {}
_DOCKER_SOCKET = os.path.realpath(
    os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock").removeprefix("unix://")
)
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class NetworkViolation(BaseException):
    """Do not let application `except Exception` hide a confinement failure."""


def reject(reason: str) -> Any:
    # Never include request headers, URLs, DSNs or inherited credentials.
    _VIOLATIONS.append(reason)
    raise NetworkViolation(f"Unmocked network operation: {reason}")


def _check_address(address: Any) -> None:
    if isinstance(address, (str, bytes)):
        if os.path.realpath(os.fsdecode(address)) == _DOCKER_SOCKET:
            return
    elif (
        isinstance(address, tuple)
        and len(address) >= 2
        and address[0] in _LOOPBACK
        and address[1] in _PORTS
    ):
        return
    reject("destination outside owned testcontainers")


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event == "socket.connect":
        _check_address(args[1])
    elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
        if args[0] not in _LOOPBACK:
            reject("external name resolution")
    elif event == "socket.getnameinfo":
        _check_address(args[0])
    elif event in {"socket.sendto", "socket.sendmsg"}:
        _check_address(args[-1] if args[-1] is not None else args[0].getpeername())
    elif event == "subprocess.Popen":
        command = args[1]
        # xdist uses pipes, not TCP. Workers load this same mandatory plugin.
        xdist = [sys.executable, "-u", "-c", "import sys;exec(eval(sys.stdin.readline()))"]
        probe = [sys.executable, "-m", "tests.network_guard_probe"]
        if command != xdist and not (
            isinstance(command, list) and command[:3] == probe and len(command) == 4
        ):
            reject("unconfined subprocess")
    elif event in {"os.system", "os.exec", "os.posix_spawn"}:
        reject("unconfined process execution")
    elif event == "open" and isinstance(args[0], (str, bytes)):
        name = Path(os.fsdecode(args[0])).name
        if name == ".env" or name.startswith(".env."):
            reject("dotenv file read")


sys.addaudithook(_audit)
# xdist only needs a banner; avoid the platform module's `uname`/`file` subprocesses.
platform.platform = lambda aliased=False, terse=False: "-".join(
    (os.uname().sysname, os.uname().release, os.uname().machine)
)

# Explicit test settings replace inherited values, before get_settings can run.
for _key in tuple(os.environ):
    if _key.upper().startswith(
        ("PADDLE_", "RESEND_", "DOCUSEAL_", "SUPABASE_", "TURNSTILE_", "PG", "POSTGRES_")
    ):
        del os.environ[_key]
os.environ.update(
    DATABASE_URL="postgresql+asyncpg://placeholder/placeholder",
    DATABASE_URL_SYNC="postgresql+psycopg2://placeholder/placeholder",
    JWT_AGENT_SECRET="test-agent-secret",
    JWT_EXPAT_SECRET="test-expat-secret",
    JWT_REFRESH_SECRET="test-refresh-secret",
    ENVIRONMENT="test",
    MOCK_SERVICES="true",
    MOCK_EMAIL="true",
    MOCK_STORAGE="true",
    AI_TRANSLATION_API_KEY="",
    SCHEDULER_ENABLED="false",
    SIGNATURES_ENABLED="false",
    BILLING_CHECKOUT_ENABLED="false",
    TESTCONTAINERS_RYUK_DISABLED="true",
    TESTCONTAINERS_HOST_OVERRIDE="127.0.0.1",
    DOCKER_AUTH_CONFIG="",
)

# libpq opens sockets in C, outside CPython socket audit events.
import psycopg2  # noqa: E402
import pytest  # noqa: E402
from docker import APIClient  # noqa: E402
from docker.models.images import ImageCollection  # noqa: E402
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

DotEnvSettingsSource._read_env_files = lambda self: {}  # type: ignore[method-assign]
_CONNECT = psycopg2.connect
_START = PostgresContainer.start
_STOP = PostgresContainer.stop
_CREATE_CONTAINER = APIClient.create_container
_EXEC_CREATE = APIClient.exec_create


def _connect(dsn: str | None = None, *args: Any, **kwargs: Any) -> Any:
    coordinates = psycopg2.extensions.parse_dsn(dsn or "") | kwargs
    host = coordinates.get("host")
    port = coordinates.get("port")
    if host not in _LOOPBACK or not str(port).isdigit() or int(port) not in _PORTS:
        reject("libpq outside owned testcontainers")
    if coordinates.get("hostaddr") not in (None, "127.0.0.1", "::1") or coordinates.get("service"):
        reject("libpq destination override")
    return _CONNECT(dsn, *args, **kwargs)


def _start(pg: PostgresContainer) -> PostgresContainer:
    if not os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock").startswith("unix://"):
        reject("remote Docker daemon")
    if pg.image != "postgres:16-alpine" or pg.volumes or pg._kwargs or pg._network:
        reject("container outside PostgreSQL harness")
    if (pg.username, pg.password, pg.dbname, pg.port) != ("test", "test", "test", 5432):
        reject("non-test PostgreSQL configuration")
    if pg._command not in (
        None,
        "postgres -c fsync=off -c synchronous_commit=off -c full_page_writes=off -c autovacuum=off",
    ):
        reject("container command outside PostgreSQL harness")
    # Bind only on loopback and request a new ephemeral port from Docker.
    pg.ports = {5432: ("127.0.0.1", None)}
    token = _STARTING.set(True)
    try:
        result = _START(pg)
    finally:
        _STARTING.reset(token)
    port = int(pg.get_exposed_port(5432))
    if port <= 5435:
        _STOP(pg)
        reject("reserved database port")
    _PORTS.add(port)
    _OWNED[pg.get_wrapped_container().id] = port
    return result


def _stop(pg: PostgresContainer, *args: Any, **kwargs: Any) -> Any:
    container = pg.get_wrapped_container()
    try:
        return _STOP(pg, *args, **kwargs)
    finally:
        port = _OWNED.pop(container.id, None)
        if port is not None:
            _PORTS.discard(port)


def _create_container(*args: Any, **kwargs: Any) -> Any:
    if not _STARTING.get():
        reject("container creation outside PostgreSQL harness")
    return _CREATE_CONTAINER(*args, **kwargs)


def _exec_create(*args: Any, **kwargs: Any) -> Any:
    if not _STARTING.get():
        reject("container command outside PostgreSQL readiness check")
    return _EXEC_CREATE(*args, **kwargs)


APIClient.create_container = _create_container
APIClient.exec_create = _exec_create
APIClient.pull = lambda *a, **kw: reject("image pull during tests")
APIClient.build = lambda *a, **kw: reject("image build during tests")
psycopg2.connect = _connect
PostgresContainer.start = _start
PostgresContainer.stop = _stop
ImageCollection.pull = lambda *a, **kw: reject("image pull during tests")


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    if not config.pluginmanager.hasplugin("tests.network_guard"):
        raise pytest.UsageError("tests.network_guard must be loaded before collection")


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item):
    before = len(_VIOLATIONS)
    yield
    if len(_VIOLATIONS) != before:
        pytest.exit("Unmocked network attempt detected, including caught exceptions", returncode=1)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    if _VIOLATIONS:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    if hasattr(session.config, "workeroutput"):
        session.config.workeroutput["network_violations"] = len(_VIOLATIONS)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: Any) -> None:
    count = getattr(node, "workeroutput", {}).get("network_violations", 0)
    _VIOLATIONS.extend(["worker reported forbidden network attempt"] * count)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    terminalreporter.write_line(f"Network guard: {len(_VIOLATIONS)} unmocked attempts")
