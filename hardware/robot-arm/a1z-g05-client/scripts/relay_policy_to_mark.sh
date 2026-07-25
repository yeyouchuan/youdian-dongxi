#!/usr/bin/env bash
set -euo pipefail

DGX_HOST="${DGX_HOST:-dgx}"
# Normal OpenSSH is required for -R forwarding. This MagicDNS FQDN routes over
# Tailscale and uses the same Tailscale SSH server as `tailscale ssh mark`.
MARK_HOST="${MARK_HOST:-mark.tail25ef30.ts.net}"
POLICY_PORT="${POLICY_PORT:-8765}"
LOCAL_BRIDGE_PORT="${LOCAL_BRIDGE_PORT:-18765}"
HERE="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
  if [[ -n "${COMMAND_PROXY_PID:-}" ]]; then
    kill "$COMMAND_PROXY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Opening command proxy Mac:127.0.0.1:${LOCAL_BRIDGE_PORT} -> ${DGX_HOST}:127.0.0.1:${POLICY_PORT}"
python3 "$HERE/ssh_command_proxy.py" \
  --listen-port "$LOCAL_BRIDGE_PORT" \
  --ssh-host "$DGX_HOST" \
  --target-port "$POLICY_PORT" &
COMMAND_PROXY_PID=$!

for _ in $(seq 1 20); do
  if bash -c "</dev/tcp/127.0.0.1/${LOCAL_BRIDGE_PORT}" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$COMMAND_PROXY_PID" 2>/dev/null; then
    echo "DGX SSH command proxy exited before becoming ready" >&2
    exit 1
  fi
  sleep 0.25
done
if ! bash -c "</dev/tcp/127.0.0.1/${LOCAL_BRIDGE_PORT}" 2>/dev/null; then
  echo "DGX SSH command proxy did not become ready" >&2
  exit 1
fi

echo "Relaying mark:127.0.0.1:${POLICY_PORT} -> Mac:127.0.0.1:${LOCAL_BRIDGE_PORT}"
echo "Keep this process running while the robot client is active."
ssh \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 \
  -N \
  -R "127.0.0.1:${POLICY_PORT}:127.0.0.1:${LOCAL_BRIDGE_PORT}" \
  "$MARK_HOST"
