#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GALAXEA_VLA_DIR:-$HOME/GalaxeaVLA}"
PYTHON="${G05_PYTHON:-$PROJECT/.venv-g05/bin/python}"

[[ "$(uname -m)" == "aarch64" ]] || { echo "FAIL: expected ARM64 DGX Spark" >&2; exit 1; }
[[ -x "$PYTHON" ]] || { echo "FAIL: missing $PYTHON" >&2; exit 1; }
[[ -f "$PROJECT/checkpoints/g05-base/checkpoints/model_state_dict.pt" ]] || {
  echo "FAIL: G0.5 base training checkpoint is missing; authenticate and download it first." >&2
  exit 1
}
[[ -f "$PROJECT/checkpoints/action_tokenizer.pt" ]] || {
  echo "FAIL: action tokenizer checkpoint is missing." >&2
  exit 1
}
[[ -d "$PROJECT/checkpoints/qwen3_5_2b_base_processor" ]] || {
  echo "FAIL: Qwen processor assets are missing." >&2
  exit 1
}

"$PYTHON" - <<'PY'
import importlib
import os
import torch

if not torch.cuda.is_available():
    raise SystemExit("FAIL: CUDA is unavailable")
available_gib = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30
if available_gib < 70:
    raise SystemExit(f"FAIL: only {available_gib:.1f} GiB unified memory available")
required = ("accelerate", "deepspeed", "hydra", "liger_kernel", "transformers")
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(f"{name}: {exc}")
if missing:
    raise SystemExit("FAIL: training dependencies unavailable:\n" + "\n".join(missing))
print("PASS:", torch.cuda.get_device_name(0), f"{available_gib:.1f} GiB available")
PY
