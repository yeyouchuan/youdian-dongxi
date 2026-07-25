#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GALAXEA_VLA_DIR:-$HOME/GalaxeaVLA}"
HF="${HF_BIN:-$PROJECT/.venv-g05/bin/hf}"

[[ -x "$HF" ]] || { echo "Missing Hugging Face CLI: $HF" >&2; exit 1; }
WHOAMI="$("$HF" auth whoami 2>&1 || true)"
if [[ -z "$WHOAMI" || "$WHOAMI" == *"Not logged in"* ]]; then
  echo "DGX is not authenticated to Hugging Face." >&2
  echo "First accept the OpenGalaxea/G05 license in your browser, then run:" >&2
  echo "  $HF auth login" >&2
  exit 1
fi

mkdir -p "$PROJECT/checkpoints"
exec "$HF" download OpenGalaxea/G05 \
  --repo-type model \
  --local-dir "$PROJECT/checkpoints" \
  --include \
    "g05-base/*" \
    "g05-so101/*" \
    "action_tokenizer.pt" \
    "qwen3_5_2b_base_processor/*"
