# Launch the A1Z x G0.5 Gradio control panel on Windows.
#
# Prereqs (once):
#   py -3.10 -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   pip install -r requirements.txt
#
# The G0.5 policy server must already be running (see start_server.ps1) and be
# reachable at the host/port in config.yaml (localhost when on the same PC).
#
# Usage:
#   .\run_app.ps1                 # uses config.yaml
#   .\run_app.ps1 --port 7861     # extra args are forwarded to a1z_g05.app

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = "$Here;$env:PYTHONPATH"

python -m a1z_g05.app --config "$Here\config.yaml" @args
