#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${G05_STATE_DIR:-$HOME/.local/state/g05}"
mkdir -p "$STATE_DIR"

"$SCRIPT_DIR/bootstrap_wsl_g05.sh" >>"$STATE_DIR/bootstrap.log" 2>&1 &
bootstrap_pid=$!

cleanup() {
  kill "$bootstrap_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait "$bootstrap_pid"
printf 'G0.5 bootstrap finished. Keeping WSL alive for remote services.\n'
while :; do
  sleep 3600
done
