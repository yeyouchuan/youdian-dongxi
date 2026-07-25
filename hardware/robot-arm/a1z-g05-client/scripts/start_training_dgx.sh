#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GALAXEA_VLA_DIR:-$HOME/GalaxeaVLA}"
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <task-config> [finetune options and Hydra overrides...]" >&2
  echo "Example dry run: $0 so100 --dry-run --max_datasets 1" >&2
  exit 2
fi

bash "$(dirname "$0")/preflight_dgx_training.sh"
cd "$PROJECT"
export PATH="$PROJECT/.venv-g05/bin:$PATH"
export PYTHONPATH="$PROJECT/src:$PROJECT:${PYTHONPATH:-}"
exec bash scripts/run/finetune.sh 1 "$@"
