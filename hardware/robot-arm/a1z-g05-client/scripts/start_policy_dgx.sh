#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GALAXEA_VLA_DIR:-$HOME/GalaxeaVLA}"
PYTHON="${G05_PYTHON:-$PROJECT/.venv-g05/bin/python}"
CHECKPOINT="${G05_CHECKPOINT:-$PROJECT/checkpoints/g05-so101/checkpoints/model_state_dict.pt}"
PORT="${POLICY_PORT:-8765}"

[[ -x "$PYTHON" ]] || { echo "Missing G0.5 Python: $PYTHON" >&2; exit 1; }
[[ -f "$CHECKPOINT" ]] || { echo "Missing checkpoint: $CHECKPOINT" >&2; exit 1; }

cd "$PROJECT"
export PYTHONPATH="$PROJECT/src:$PROJECT:${PYTHONPATH:-}"
exec "$PYTHON" scripts/serve_policy.py \
  --ckpt_path "$CHECKPOINT" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --device cuda \
  --action_steps 16 \
  eval_embodiment=so100 \
  model.model_weights_to_bf16=true \
  model.use_torch_compile=false \
  model.model_arch.attn_implementation=sdpa
