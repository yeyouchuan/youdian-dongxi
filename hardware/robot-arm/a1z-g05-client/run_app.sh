#!/usr/bin/env bash
# Launch the A1Z x G0.5 Gradio control panel on the macOS laptop.
#
# Prereqs (once):
#   python3 -m venv .venv && source .venv/bin/activate
#   pip install -r requirements.txt
#
# The remote G0.5 policy server must already be running on a CUDA GPU box, e.g.:
#   bash GalaxeaVLA/experiments/so100/start_server.sh /path/to/g05-so101.pt
# and reachable at the host/port set in config.yaml (use an SSH tunnel if needed:
#   ssh -N -L 8765:localhost:8765 user@gpu-box).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$HERE:${PYTHONPATH:-}"

python -m a1z_g05.app --config "$HERE/config.yaml" "$@"
