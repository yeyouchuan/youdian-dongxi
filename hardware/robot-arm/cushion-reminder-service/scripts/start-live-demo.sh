#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
robot_arm_dir="$(cd "${service_dir}/.." && pwd)"
broker_config="${service_dir}/config/broker.lan-demo.yaml"
runtime_env="${CUSHION_RUNTIME_ENV:-${HOME}/.config/cushion-reminder/runtime.env}"

if [[ -f "${runtime_env}" ]]; then
  runtime_mode="$(stat -f '%Lp' "${runtime_env}" 2>/dev/null || stat -c '%a' "${runtime_env}")"
  if (( (8#${runtime_mode} & 8#077) != 0 )); then
    echo "Runtime env must not be group/world readable: ${runtime_env}" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "${runtime_env}"
  set +a
fi

MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
MQTT_PORT="${MQTT_PORT:-1883}"
MQTT_TRANSPORT="${MQTT_TRANSPORT:-tcp}"
MARK_SSH_HOST="${MARK_SSH_HOST:-mark}"
CUSHION_SEATED_THRESHOLD_SECONDS="${CUSHION_SEATED_THRESHOLD_SECONDS:-60}"
VISION_MAX_FRAME_AGE_SECONDS="${VISION_MAX_FRAME_AGE_SECONDS:-8}"

broker_pid=""
relay_pid=""

cleanup() {
  for child in "${relay_pid}" "${broker_pid}"; do
    if [[ -n "${child}" ]]; then
      kill "${child}" 2>/dev/null || true
      wait "${child}" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

port_open() {
  python3 - "$1" <<'PY'
import socket
import sys

try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=0.2):
        pass
except OSError:
    raise SystemExit(1)
PY
}

wait_for_port() {
  local port="$1"
  local description="$2"
  for _ in {1..100}; do
    if port_open "${port}"; then
      return
    fi
    sleep 0.1
  done
  echo "${description} did not become ready on port ${port}" >&2
  exit 1
}

if port_open 1883 || port_open 9001; then
  if ! port_open 1883 || ! port_open 9001; then
    echo "Only one MQTT listener is active; expected both TCP 1883 and WebSocket 9001" >&2
    exit 1
  fi
  echo "Reusing MQTT broker already listening on 127.0.0.1:1883 and :9001"
else
  echo "Starting LAN MQTT broker (TCP 1883 + WebSocket 9001)"
  uvx --from "amqtt>=0.11,<0.12" amqtt -c "${broker_config}" &
  broker_pid=$!
  wait_for_port 1883 "MQTT TCP listener"
  wait_for_port 9001 "MQTT WebSocket listener"
fi

if ssh -o BatchMode=yes -o ConnectTimeout=5 "${MARK_SSH_HOST}" \
  "ss -lnt | grep -q '127.0.0.1:8765'"; then
  echo "Reusing Mark policy relay on 127.0.0.1:8765"
else
  echo "Starting DGX G0.5 -> Mark policy relay"
  bash "${robot_arm_dir}/a1z-g05-client/scripts/relay_policy_to_mark.sh" &
  relay_pid=$!
  for _ in {1..100}; do
    if ssh -o BatchMode=yes -o ConnectTimeout=5 "${MARK_SSH_HOST}" \
      "ss -lnt | grep -q '127.0.0.1:8765'"; then
      break
    fi
    if ! kill -0 "${relay_pid}" 2>/dev/null; then
      wait "${relay_pid}"
    fi
    sleep 0.2
  done
fi

lan_ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
echo "Web console: http://127.0.0.1:3000"
if [[ -n "${lan_ip}" ]]; then
  echo "TestFlight broker: ws://${lan_ip}:9001"
  echo "ESP32 broker host: ${lan_ip}, TCP port 1883"
fi
echo "The robot preflight will remain locked until Mark exposes a camera under /dev/video*."

env \
  ROBOT_EXECUTION_MODE=ssh-mark \
  MARK_SSH_HOST="${MARK_SSH_HOST}" \
  ALLOW_MOUNTED_AS_EXTERIOR=1 \
  MQTT_HOST="${MQTT_HOST}" \
  MQTT_PORT="${MQTT_PORT}" \
  MQTT_TRANSPORT="${MQTT_TRANSPORT}" \
  CUSHION_SEATED_THRESHOLD_SECONDS="${CUSHION_SEATED_THRESHOLD_SECONDS}" \
  VISION_MAX_FRAME_AGE_SECONDS="${VISION_MAX_FRAME_AGE_SECONDS}" \
  uv run --project "${service_dir}" cushion-web --host 127.0.0.1 --port 3000
