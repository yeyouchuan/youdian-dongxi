#!/usr/bin/env bash
set -euo pipefail

CLIENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
A1Z_DIR="${A1Z_DIR:-$HOME/GALAXEA-A1Z}"
PYTHON="${A1Z_PYTHON:-$A1Z_DIR/.venv/bin/python}"
LOG_DIR="${A1Z_STATE_DIR:-$HOME/.local/state/a1z}"

[[ -x "$PYTHON" ]] || { echo "Missing A1Z Python: $PYTHON" >&2; exit 1; }
[[ -d "$A1Z_DIR/a1z" ]] || { echo "Missing A1Z source: $A1Z_DIR" >&2; exit 1; }
[[ ! -S /tmp/a1z.sock ]] || {
  echo "An A1Z server is already active at /tmp/a1z.sock; stop it explicitly first." >&2
  exit 1
}

mkdir -p "$LOG_DIR"
cd "$CLIENT_DIR"
exec "$PYTHON" -m a1z_g05.safe_server \
  --a1z-dir "$A1Z_DIR" \
  --can can0 \
  --control-hz 50 \
  --min-hz 40 \
  --watchdog-s 0.35 \
  >>"$LOG_DIR/server.log" 2>&1
