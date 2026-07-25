#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
broker_config="${service_dir}/config/broker.development.yaml"

broker_pid=""
cleanup() {
  if [[ -n "${broker_pid}" ]]; then
    kill "${broker_pid}" 2>/dev/null || true
    wait "${broker_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

uvx --from "amqtt>=0.11,<0.12" amqtt -c "${broker_config}" &
broker_pid=$!

broker_ready=false
for _ in {1..200}; do
  if python3 - "${broker_pid}" <<'PY'
import socket
import sys

broker_pid = int(sys.argv[1])
try:
    with socket.create_connection(("127.0.0.1", 1883), timeout=0.1):
        pass
except OSError:
    raise SystemExit(1)
raise SystemExit(0)
PY
  then
    broker_ready=true
    break
  fi
  if ! kill -0 "${broker_pid}" 2>/dev/null; then
    wait "${broker_pid}"
  fi
  sleep 0.1
done

if [[ "${broker_ready}" != true ]]; then
  echo "Development MQTT broker failed to start" >&2
  exit 1
fi

uv run --project "${service_dir}" cushion-simulator "$@"
