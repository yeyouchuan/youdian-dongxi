#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="${GALAXEA_VLA_DIR:-$HOME/GalaxeaVLA}"
HF="${HF_BIN:-$PROJECT/.venv/bin/hf}"
STATE_FILE="${G05_STATE_FILE:-$HOME/.local/state/g05/status.json}"

[[ -x "$HF" ]] || { echo "Missing Hugging Face CLI: $HF" >&2; exit 1; }
mkdir -p "$PROJECT/checkpoints" "$(dirname "$STATE_FILE")"

update_state() {
  "$PROJECT/.venv/bin/python" - "$STATE_FILE" "$1" "$2" "$3" <<'PY'
import json
import os
import sys
import tempfile
import time

path, phase, message, detail = sys.argv[1:]
try:
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
except (OSError, json.JSONDecodeError):
    state = {}
state.update(
    {
        "timestamp": time.time(),
        "phase": phase,
        "overall": "starting",
        "message": message,
        "install_status": "running",
        "install_detail": detail,
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

update_state \
  "checkpoint download" \
  "Downloading only the SO-101 G0.5 checkpoint and shared assets." \
  "OpenGalaxea/G05: g05-so101, action tokenizer, processor"

cd "$PROJECT"
"$HF" download OpenGalaxea/G05 \
  --repo-type model \
  --local-dir checkpoints \
  --include \
    "g05-so101/**" \
    "action_tokenizer.pt" \
    "qwen3_5_2b_base_processor/**"

required=(
  "checkpoints/action_tokenizer.pt"
  "checkpoints/g05-so101/.hydra/config.yaml"
  "checkpoints/g05-so101/checkpoints/model_state_dict.pt"
  "checkpoints/g05-so101/dataset_stats.json"
)
for path in "${required[@]}"; do
  [[ -f "$path" ]] || { echo "Checkpoint download incomplete: $path" >&2; exit 1; }
done

update_state \
  "checkpoint download" \
  "SO-101 checkpoint download complete." \
  "Checkpoint and required sidecars verified."
