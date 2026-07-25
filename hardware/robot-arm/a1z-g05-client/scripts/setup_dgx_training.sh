#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GALAXEA_VLA_DIR:-$HOME/GalaxeaVLA}"
UV="${UV_BIN:-$HOME/.local/bin/uv}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

bash "$HERE/scripts/setup_dgx_inference.sh"
"$UV" pip install --python "$PROJECT/.venv-g05/bin/python" \
  -r "$HERE/requirements-dgx-training.txt"

if [[ "${INSTALL_G05_NATIVE_KERNELS:-0}" == "1" ]]; then
  "$UV" pip install --python "$PROJECT/.venv-g05/bin/python" \
    "flash-linear-attention>=0.2.0" "flash-attn-4>=4.0.0b15"
else
  echo "Native flash kernels skipped on ARM64."
  echo "Validate SDPA first; set INSTALL_G05_NATIVE_KERNELS=1 to build them explicitly."
fi
