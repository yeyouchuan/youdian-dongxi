#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="${GALAXEA_VLA_DIR:-$HOME/GalaxeaVLA}"
PYTHON="${G05_PYTHON:-$PROJECT/.venv/bin/python}"
CHECKPOINT="${G05_CHECKPOINT:-$PROJECT/checkpoints/g05-so101/checkpoints/model_state_dict.pt}"
PORT="${POLICY_PORT:-8765}"
STATE_DIR="${G05_STATE_DIR:-$HOME/.local/state/g05}"
STATE_FILE="$STATE_DIR/status.json"
LOG_FILE="$STATE_DIR/policy.log"

[[ -x "$PYTHON" ]] || { echo "Missing G0.5 Python: $PYTHON" >&2; exit 1; }
[[ -f "$CHECKPOINT" ]] || { echo "Missing checkpoint: $CHECKPOINT" >&2; exit 1; }
mkdir -p "$STATE_DIR"

update_state() {
  "$PYTHON" - "$STATE_FILE" "$1" "$2" "$3" <<'PY'
import json
import os
import sys
import tempfile
import time

path, status, message, detail = sys.argv[1:]
try:
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
except (OSError, json.JSONDecodeError):
    state = {}
state.update(
    {
        "timestamp": time.time(),
        "phase": "policy startup",
        "overall": "starting" if status != "error" else "error",
        "message": message,
        "policy_status": status,
        "policy_detail": detail,
    }
)
with tempfile.NamedTemporaryFile(
    "w", dir=os.path.dirname(path), delete=False, encoding="utf-8"
) as handle:
    json.dump(state, handle, ensure_ascii=False)
    temporary = handle.name
os.replace(temporary, path)
PY
}

update_state "loading" "Loading G0.5 SO-101 on the RTX 4060." \
  "BF16 + SDPA; torch.compile disabled for the 8 GiB GPU"

cd "$PROJECT"
export PYTHONPATH="$PROJECT/src:$PROJECT:${PYTHONPATH:-}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True,max_split_size_mb:128}"

set +e
"$PYTHON" scripts/serve_policy.py \
  --ckpt_path "$CHECKPOINT" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --device cuda \
  --action_steps 16 \
  eval_embodiment=so100 \
  model.model_weights_to_bf16=true \
  model.use_torch_compile=false \
  model.model_arch.attn_implementation=sdpa \
  2>&1 | tee "$LOG_FILE"
exit_code="${PIPESTATUS[0]}"
set -e

update_state "error" "The G0.5 policy process exited." "$(tail -n 12 "$LOG_FILE")"
exit "$exit_code"
