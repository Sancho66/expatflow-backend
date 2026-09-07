"""Fixed, confined child scenarios used to test the guard's failure exit status."""

import sys
import tempfile
from pathlib import Path

from tests import network_guard  # noqa: F401

# No user-supplied code or command is accepted by this subprocess entry point.
SCENARIOS = {
    "ipv6": """
import socket
def test_ipv6(): socket.socket(socket.AF_INET6).connect(('2001:db8::1', 443))
""",
    "unix": """
import socket
def test_unix(): socket.socket(socket.AF_UNIX).connect('/tmp/unowned-provider.sock')
""",
    "getnameinfo": """
import socket
def test_nameinfo(): socket.getnameinfo(('192.0.2.1', 443), 0)
""",
    "caught": """
import socket
def test_caught():
 try: socket.create_connection(('192.0.2.1', 443))
 except BaseException: pass
""",
    "collect": """
import socket
try: socket.getaddrinfo('provider.invalid', 443)
except BaseException: pass
def test_ok(): pass
""",
    "fixture": """
import socket, pytest
@pytest.fixture(autouse=True)
def setup():
 try: socket.socket().connect(('127.0.0.1', 5435))
 except BaseException: pass
def test_ok(): pass
""",
    "dns": """
import socket
def test_dns(): socket.getaddrinfo('provider.invalid', 443)
""",
    "udp": """
import socket
def test_udp(): socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'x', ('192.0.2.1', 53))
""",
    "libpq": """
import psycopg2
def test_libpq():
 psycopg2.connect(host='127.0.0.1', port=5435, user='test', password='test', dbname='test')
""",
    "subprocess": """
import subprocess
def test_process(): subprocess.run(['curl', 'https://provider.invalid'], check=True)
""",
    "httpx": """
import httpx
def test_httpx(): httpx.get('https://provider.invalid')
""",
    "mock": """
import httpx
def test_mock():
 with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
  assert c.get('https://provider.invalid').status_code == 200
""",
}


def main() -> int:
    import pytest

    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        return 2
    with tempfile.TemporaryDirectory(prefix="network-guard-probe-") as root:
        target = Path(root) / "test_probe.py"
        target.write_text(SCENARIOS[sys.argv[1]])
        return int(
            pytest.main(
                [
                    "-c",
                    str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
                    "--confcutdir",
                    root,
                    "-o",
                    "addopts=",
                    "-p",
                    "tests.network_guard",
                    "-p",
                    "no:cacheprovider",
                    "-q",
                    str(target),
                ]
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
