#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GALAXEA_VLA_DIR:-$HOME/GalaxeaVLA}"
UV="${UV_BIN:-$HOME/.local/bin/uv}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

[[ "$(uname -m)" == "aarch64" ]] || {
  echo "This setup is specifically for the ARM64 DGX Spark." >&2
  exit 1
}
[[ -d "$PROJECT/.git" ]] || {
  echo "Missing official GalaxeaVLA checkout at $PROJECT" >&2
  exit 1
}

if [[ ! -x "$UV" ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

"$UV" python install 3.10.16
if [[ ! -x "$PROJECT/.venv-g05/bin/python" ]]; then
  "$UV" venv --python 3.10.16 "$PROJECT/.venv-g05"
fi
"$UV" pip install --python "$PROJECT/.venv-g05/bin/python" \
  torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
  --index-url https://download.pytorch.org/whl/cu128
"$UV" pip install --python "$PROJECT/.venv-g05/bin/python" \
  -r "$HERE/requirements-dgx-inference.txt"
"$UV" pip install --python "$PROJECT/.venv-g05/bin/python" \
  --no-deps --editable "$PROJECT"

"$PROJECT/.venv-g05/bin/python" - <<'PY'
import platform
import torch

print("machine:", platform.machine())
print("torch:", torch.__version__)
print("cuda:", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available")
print("device:", torch.cuda.get_device_name(0))
PY
