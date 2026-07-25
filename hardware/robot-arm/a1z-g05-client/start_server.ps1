# Start the G0.5 policy server on Windows (CUDA), single-arm so100 embodiment.
#
# Runs inside the GalaxeaVLA repo's environment. Uses the SDPA attention path so
# flash-attn (hard to build on Windows) is NOT required.
#
# Prereqs (once), inside the GalaxeaVLA checkout:
#   py -3.10 -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128
#   pip install -e .            # or: uv sync --index-strategy unsafe-best-match
#   huggingface-cli download OpenGalaxea/G05 --repo-type model --local-dir checkpoints
#
# Usage (from anywhere):
#   .\start_server.ps1 -GalaxeaVLA C:\path\to\GalaxeaVLA
#   .\start_server.ps1 -GalaxeaVLA C:\path\to\GalaxeaVLA -Ckpt checkpoints\g05-so101\checkpoints\model_state_dict.pt

param(
    [Parameter(Mandatory = $true)] [string] $GalaxeaVLA,
    [string] $Ckpt = "checkpoints\g05-so101\checkpoints\model_state_dict.pt",
    [int]    $Port = 8765,
    [int]    $ActionSteps = 32
)

$ErrorActionPreference = "Stop"
Set-Location $GalaxeaVLA
$env:PYTHONPATH = "$GalaxeaVLA\src;$env:PYTHONPATH"

Write-Host "Starting G0.5 so100 policy server on port $Port ..."
Write-Host "  ckpt = $Ckpt"

python "$GalaxeaVLA\scripts\serve_policy.py" `
    --ckpt_path "$Ckpt" `
    --host 0.0.0.0 `
    --port $Port `
    --device cuda `
    --action_steps $ActionSteps `
    eval_embodiment=so100 `
    model.model_weights_to_bf16=true `
    model.model_arch.attn_implementation=sdpa
