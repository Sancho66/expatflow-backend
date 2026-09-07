#!/usr/bin/env bash
# A second, kernel-level barrier covers native libraries as well as Python sockets.
set -euo pipefail
cd "$(dirname "$0")/.."
readonly test_user=nidria-tests
sudo useradd --system --create-home "$test_user"
readonly test_uid="$(id -u "$test_user")"
sudo usermod -aG docker "$test_user"
# The runner's home is private. Relocate the existing code/venv without
# granting the test account access to runner credentials or installing anything.
readonly test_root="$(mktemp -d /tmp/nidria-tests.XXXXXX)"
trap 'sudo rm -rf -- "$test_root"' EXIT
tar --exclude='./.git' --exclude='./.env*' -cf - . | tar -xf - -C "$test_root"
sudo chown -R "$test_user" "$test_root"
sudo chmod 755 "$test_root"
cd "$test_root"
# Dependencies and image acquisition finish BEFORE the test process exists.
docker pull postgres:16-alpine
for firewall in iptables ip6tables; do
  sudo "$firewall" -N NIDRIA_TEST_EGRESS
  sudo "$firewall" -A OUTPUT -m owner --uid-owner "$test_uid" -j NIDRIA_TEST_EGRESS
  # Docker publishes PostgreSQL on ephemeral loopback TCP ports. The Python
  # guard narrows this range to ports actually owned by the current worker.
  # Do not allow the loopback DNS stub: it could forward a native DNS query.
  sudo "$firewall" -A NIDRIA_TEST_EGRESS -o lo -p tcp --dport 32768:65535 -j RETURN
  sudo "$firewall" -A NIDRIA_TEST_EGRESS -j REJECT
done
# Positive control: native socket code bypasses the Python plugin, but the
# kernel must reject and count a TEST-NET packet before any pytest starts.
sudo -u "$test_user" env -i /usr/bin/python3 -I -S -c '
import socket
try:
    socket.create_connection(("192.0.2.1", 443), timeout=2)
except OSError:
    pass
'
probe_count="$(sudo iptables -L NIDRIA_TEST_EGRESS -v -n -x | awk '$3 == "REJECT" {print $1}')"
if [[ ! "$probe_count" =~ ^[0-9]+$ ]] || [ "$probe_count" -eq 0 ]; then
  echo "Kernel guard positive control failed"
  exit 1
fi
echo "Kernel guard positive control: $probe_count TEST-NET packets rejected"
sudo iptables -Z NIDRIA_TEST_EGRESS
sudo ip6tables -Z NIDRIA_TEST_EGRESS
set +e
sudo -u "$test_user" env -i \
  HOME="/home/$test_user" PATH="$PWD/.venv/bin:/usr/bin:/bin" \
  DOCKER_HOST=unix:///var/run/docker.sock PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "$PWD/.venv/bin/python" -m pytest -p tests.network_guard \
  -p pytest_asyncio.plugin -p xdist.plugin tests/ -x -q -n auto
result=$?
set -e
blocked=0
for firewall in iptables ip6tables; do
  count="$(sudo "$firewall" -L NIDRIA_TEST_EGRESS -v -n -x | awk '$3 == "REJECT" {print $1}')"
  [[ "$count" =~ ^[0-9]+$ ]] || exit 1
  blocked=$((blocked + count))
done
echo "Kernel network guard: $blocked forbidden packets"
if [ "$blocked" -ne 0 ]; then
  exit 1
fi
exit "$result"
