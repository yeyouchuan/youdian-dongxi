#!/usr/bin/env bash
set -Eeuo pipefail

G05_HOME="${G05_HOME:-$HOME/GalaxeaVLA}"
STATE_DIR="${G05_STATE_DIR:-$HOME/.local/state/g05}"
STATE_FILE="$STATE_DIR/status.json"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
MONITOR_SCRIPT="${G05_MONITOR_SCRIPT:-$CLIENT_DIR/a1z_g05/monitor.py}"
PYTHON="${G05_PYTHON:-$HOME/.local/python-3.10.16/bin/python3.10}"
UV="${UV_BIN:-$HOME/.local/bin/uv}"
STATE_PYTHON="$(command -v python3 || true)"

mkdir -p "$STATE_DIR"

write_state() {
  local phase="$1"
  local overall="$2"
  local install_status="$3"
  local message="$4"
  local detail="${5:-}"
  if [[ -z "$STATE_PYTHON" ]]; then
    printf '%s: %s\n' "$phase" "$message" >&2
    return
  fi
  "$STATE_PYTHON" - "$STATE_FILE" "$phase" "$overall" "$install_status" "$message" "$detail" <<'PY'
import json
import os
import sys
import tempfile
import time

path, phase, overall, install_status, message, detail = sys.argv[1:]
state = {}
try:
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
except (OSError, json.JSONDecodeError):
    pass
state.update(
    {
        "timestamp": time.time(),
        "phase": phase,
        "overall": overall,
        "install_status": install_status,
        "install_detail": detail,
        "message": message,
    }
)
directory = os.path.dirname(path)
with tempfile.NamedTemporaryFile("w", dir=directory, delete=False, encoding="utf-8") as handle:
    json.dump(state, handle, ensure_ascii=False)
    temporary = handle.name
os.replace(temporary, path)
PY
}

require_file() {
  if [[ ! -f "$1" ]]; then
    write_state "environment setup" "error" "error" "$2" "$1"
    printf 'Missing required file: %s\n' "$1" >&2
    exit 1
  fi
}

require_file "$PYTHON" "Python 3.10.16 is missing."
require_file "$UV" "uv is missing."
require_file "$MONITOR_SCRIPT" "The G0.5 monitor script is missing."
require_file "$HOME/.local/bin/mihomo" "Mihomo is missing."
require_file "$HOME/.config/mihomo/config.yaml" "Mihomo configuration is missing."
require_file "$G05_HOME/pyproject.toml" "GalaxeaVLA checkout is missing."

if [[ -f "$HOME/.config/g05-proxy/env.sh" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.config/g05-proxy/env.sh"
fi

start_if_absent() {
  local pattern="$1"
  shift
  if ! pgrep -f "$pattern" >/dev/null; then
    setsid -f "$@"
  fi
}

start_if_absent "$HOME/.local/bin/mihomo -d" \
  "$HOME/.local/bin/mihomo" -d "$HOME/.config/mihomo"

monitor_python="$(command -v python3.11 || command -v python3)"
start_if_absent "$MONITOR_SCRIPT --host" \
  "$monitor_python" "$MONITOR_SCRIPT" --host 0.0.0.0 --port 3000

write_state \
  "dependency installation" \
  "starting" \
  "running" \
  "Installing the official G0.5 CUDA environment." \
  "uv sync --frozen; cached downloads are reused"

cd "$G05_HOME"
export CC=gcc
export CXX=g++
export UV_HTTP_TIMEOUT=3600
export UV_LINK_MODE=copy
export UV_CONCURRENT_DOWNLOADS=1

install_log="$STATE_DIR/install.log"
if "$UV" sync --frozen 2>&1 | tee "$install_log"; then
  write_state \
    "dependency installation" \
    "starting" \
    "ready" \
    "G0.5 dependencies installed; ready for CUDA validation." \
    "Official lockfile installed successfully."
else
  exit_code="${PIPESTATUS[0]}"
  write_state \
    "dependency installation" \
    "error" \
    "error" \
    "G0.5 dependency installation failed." \
    "$(tail -n 8 "$install_log")"
  exit "$exit_code"
fi
