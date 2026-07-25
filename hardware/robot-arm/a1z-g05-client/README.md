# A1Z × G0.5

Operational bridge between the Galaxea A1Z arm and the GalaxeaVLA G0.5
SO100/SO101 policy. Shadow mode and guarded real-hardware execution are both
available.

For the complete mapping and safety rationale, read
[`../docs/g05-a1z-technical-summary.md`](../docs/g05-a1z-technical-summary.md).
For the planned MQTT SmartCushion wrapper, read
[`../docs/mqtt-cushion-reminder-service-plan.md`](../docs/mqtt-cushion-reminder-service-plan.md).

## Current topology

```text
mark (WSL, robot side)               Mac relay                 DGX Spark
camera + A1Z telemetry  ──WS──────▶  reverse SSH  ──────────▶ G0.5 policy
        ▲                                                        │
        └──────── checked SO100 action chunks ◀───────────────────┘
```

- `dgx` is the CUDA host for G0.5 inference and future fine-tuning.
- `mark` (reached with `tailscale ssh mark`) owns the wrist camera and official
  A1Z SDK/safe-daemon process.
- The Mac can reach both hosts and relays DGX port 8765 into
  `mark:127.0.0.1:8765`.
- `config.mark-shadow.yaml` records and checks actions without writes.
- `config.mark-execute.yaml` enables guarded writes to the real A1Z.

The G0.5 server and robot client must remain separate. The current `mark` WSL
instance has no NVIDIA GPU, while the DGX Spark has a GB10 with 128 GB unified
memory.

## Current verified state

As of 2026-07-24, the checked-in real-hardware path has run on the A1Z:

- 50 Hz safe daemon, minimum 40 Hz and 350 ms stream watchdog;
- 15 Hz G0.5 client with 16-step action chunks;
- 640×480 MJPEG wrist camera at 5 FPS, rotated 180°;
- SO100 five-axis + gripper direct mapping to A1Z J1/J2/J3/J5/J6;
- J4 excluded from model control and held by a daemon-owned target;
- real action execution, deterministic gripper commands and neutral return;
- power-cycle encoder-turn recovery for MotorA feedback such as
  `-360°/+354°`.

Both shadow and execute configurations remain fail-closed:

- no automatic homing;
- missing or older-than-500-ms camera frames stop inference;
- malformed, non-finite, and out-of-limit actions are rejected;
- official A1Z soft limits and maximum action-step changes are checked after
  every decoded action;
- the official SDK's gripper convention is used: `0=closed`, `1=open`;
- a single-instance lock prevents competing CAN daemons;
- stale feedback, low control frequency, motor faults and over-temperature
  trigger the daemon safety path;
- disconnecting the headless client does not stop the A1Z daemon, because
  stopping it disables torque on this brake-less arm.

The SO100 checkpoint drives five arm joints plus a gripper. A1Z has six arm
joints plus a gripper. The current direct mapping is calibrated around the
SO101 proprioception distribution, but it is not an A1Z-specific fine-tuned
embodiment. J4 cannot be commanded by the model.

The current single physical camera is insufficient for reliable grasp
evaluation. Official SO100 deployment uses `exterior + wrist_right`; production
should add one fixed exterior camera and only zero-pad `wrist_left`.

Read the parent [robot safety guide](../README.md) before enabling the arm.
Do not issue prompts that request touching, poking or striking a real person.
Use a non-contact reminder gesture or a fixed instrumented foam target.

## 1. DGX policy service

The official checkout is expected at `~/GalaxeaVLA`, with a Python 3.10
environment at `~/GalaxeaVLA/.venv-g05` and the official checkpoint at:

```text
~/GalaxeaVLA/checkpoints/g05-so101/checkpoints/model_state_dict.pt
```

The upstream full dependency lock includes x86-only simulation packages such
as `coacd`, so it cannot be installed unchanged on the ARM64 DGX Spark.
Install a dedicated inference/training environment without the simulation
extras. PyTorch 2.7.1 cu128 has an ARM64 wheel and is usable on this host.

```bash
ssh dgx
cd ~/hardware/robot-arm/a1z-g05-client
bash scripts/setup_dgx_inference.sh
```

The model repository is license-gated. Accept the
`OpenGalaxea/G05` terms in Hugging Face, authenticate once on DGX, and download
the base training checkpoint, SO101 inference checkpoint, action tokenizer,
and processor assets:

```bash
~/GalaxeaVLA/.venv-g05/bin/hf auth login
bash scripts/download_g05_artifacts.sh
```

Start the policy server on DGX:

```bash
ssh dgx
cd ~/hardware/robot-arm/a1z-g05-client
bash scripts/start_policy_dgx.sh
```

The launcher uses SDPA and disables `torch.compile`, which avoids treating the
SO100 x86 deployment flags as if they had already been validated on GB10.

G0.5 inference can block the policy server event loop for more than the
WebSocket library's default 20-second ping window. Apply the version-controlled
keepalive patch to the DGX GalaxeaVLA checkout once:

```bash
cd ~/GalaxeaVLA
git apply ~/hardware/robot-arm/a1z-g05-client/patches/serve-policy-disable-ping.patch
```

The patch disables protocol pings on the policy server. Mark still bounds each
inference response to 120 seconds, while the scenario service keeps its
independent 175-second remote process timeout and the safe daemon watchdog.

For the training workload, install the incremental training dependencies and
run the official single-GPU launcher:

```bash
bash scripts/setup_dgx_training.sh
bash scripts/start_training_dgx.sh so100 --dry-run --max_datasets 1
# Replace the dry-run arguments with the calibrated A1Z dataset/config once ready.
```

The preflight requires at least 70 GiB currently available unified memory and
refuses to launch before the gated base/SO101 artifacts are present.

### Windows WSL direct inference

For the current RTX 4060 Laptop deployment, keep a WSL terminal open and run:

```bash
cd ~/hardware-repo/robot-arm/a1z-g05-client
bash scripts/keep_wsl_g05_alive.sh
```

This resumes the official frozen-lock dependency installation with one
concurrent download, starts the local Mihomo proxy and read-only monitor, and
keeps WSL alive after installation. Cached `uv` downloads are reused. The
monitor is available over Tailscale at `http://100.120.236.41:3000`.
It has no motion controls, but it listens on `0.0.0.0`; restrict port 3000 to
the Tailscale/private network with the Windows firewall.

The laptop GPU has 8 GiB VRAM, below the upstream recommendation. Policy
startup must therefore keep BF16 and SDPA enabled and disable
`torch.compile`; successful startup still depends on the checkpoint fitting
at runtime.

## 2. Relay DGX to mark

DGX is currently reachable on the Mac's LAN but is not a Tailscale peer.
`mark` is a remote Tailscale host and cannot reach the DGX LAN directly.
Keep this relay running on the Mac:

```bash
cd robot-arm/a1z-g05-client
bash scripts/relay_policy_to_mark.sh
```

It creates:

```text
mark:127.0.0.1:8765 -> DGX-LAN-IP:8765
```

No public listener is created on `mark`.

## 3. mark robot-side preflight

The A1Z safe daemon must be started separately and remain owned by the
operator. It exposes `/tmp/a1z.sock`, owns the 50 Hz CAN loop and includes
gripper telemetry and guarded stream writes.

Start exactly one daemon:

```bash
tailscale ssh mark
cd ~/hardware/robot-arm/a1z-g05-client
nohup bash scripts/start_a1z_safe_server.sh \
  >> ~/.local/state/a1z/server-launch.log 2>&1 </dev/null &
```

If `/tmp/a1z.sock` already exists, inspect the existing process instead of
starting another one:

```bash
pgrep -af '[a]1z_g05.safe_server'
~/GALAXEA-A1Z/.venv/bin/python ~/GALAXEA-A1Z/tools/a1zctl status
```

Before starting the client:

```bash
tailscale ssh mark
cd ~/hardware/robot-arm/a1z-g05-client
bash scripts/preflight_mark.sh --operator-checked
```

The preflight is read-only. It requires:

- `/dev/video*`;
- SocketCAN `can0`;
- `/tmp/a1z.sock`;
- the policy relay on `127.0.0.1:8765`.

USB/IP attachment can disappear after Windows/WSL restart or USB reset.
Preflight must therefore run on every powered session even when the previous
session succeeded.

Start the shadow client:

```bash
~/.local/python-3.10.16/bin/python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m a1z_g05.app --config config.mark-shadow.yaml --host 127.0.0.1
```

Open `http://127.0.0.1:7860` on `mark`, or forward it over SSH.

Run one guarded headless task:

```bash
PYTHONPATH=. ~/GALAXEA-A1Z/.venv/bin/python -m a1z_g05.headless \
  --config config.mark-execute.yaml \
  --task "Move toward the visible object, grasp it, lift it, and stop." \
  --max-steps 64
```

Use deterministic control—not a prompt—for exact poses and recovery:

```bash
~/GALAXEA-A1Z/.venv/bin/python ~/GALAXEA-A1Z/tools/a1zctl \
  move 0,60,-60,0,0,0 --speed 0.15
```

## Mapping and camera gates

Two mapping implementations exist:

- `mode: direct` is the current real-hardware path. It maps SO100 to A1Z
  J1/J2/J3/J5/J6 and locks J4.
- `mode: kinematic` performs FK → configurable frame transform → IK. Its frame
  transform still requires paired calibration before real execution.

Kinematic calibration requires:

1. record synchronized A1Z joint/gripper state and wrist frames;
2. convert SO100 joint samples to end-effector poses with SO100 FK;
3. transform those poses into the A1Z base/camera frame;
4. solve A1Z IK with the official URDF and soft limits;
5. calibrate gripper open/closed values;
6. validate trajectories in simulation and then at reduced speed;
7. validate the transformed mapping in shadow mode before real writes.

The asynchronous stream writer, watchdog and execute configuration now exist.
The blocking `a1zctl move` RPC is reserved for deterministic recovery and exact
poses; it is not used for the 15 Hz policy stream.

The safe daemon also exposes a socket-only Cartesian correction primitive for
the higher-level visual workflow:

```json
{"cmd":"move_tool_delta","args":{"frame":"base","delta_m":[0,0,0.01],"speed":0.08}}
```

It uses `A1Z_G1Z.urdf`, position-only IK with J4 locked, and rejects a waypoint
when any component exceeds 20 mm, the vector exceeds 30 mm, a solved joint
changes more than 8°, limits are violated, temperatures/faults are unsafe, or a
policy stream is active. Success additionally requires the measured TCP to move
in the requested direction within tolerance and locked-J4 drift to remain at or
below 1°. An IK solution alone is never reported as physical success.

Camera modes:

- `config.mark-execute.yaml`: physical camera as `wrist_right`; `exterior` and
  `wrist_left` are black.
- `config.mark-execute-exterior.yaml`: diagnostic A/B with the same physical
  camera as `exterior`; both wrist slots are black.
- target production mode: fixed physical `exterior` + arm-mounted
  `wrist_right`; only `wrist_left` is black.

## Important files

| Path | Purpose |
| --- | --- |
| `a1z_g05/headless.py` | one-shot task runner used by automation |
| `a1z_g05/controller.py` | observation/action loop and client safety |
| `a1z_g05/mapping.py` | direct SO100↔A1Z conversion |
| `a1z_g05/retargeting.py` | optional FK/IK mapping |
| `a1z_g05/safe_server.py` | real-time daemon, singleton lock and watchdog |
| `a1z_g05/camera.py` | UVC capture and orientation |
| `a1z_g05/g05_client.py` | msgpack WebSocket client |
| `scripts/start_policy_dgx.sh` | DGX inference launcher |
| `scripts/relay_policy_to_mark.sh` | private Mac relay |
| `scripts/start_a1z_safe_server.sh` | Mark safe daemon launcher |
| `scripts/preflight_mark.sh` | read-only hardware/policy readiness gate |
| `scripts/bootstrap_wsl_g05.sh` | resumable WSL dependency/bootstrap workflow |
| `scripts/download_g05_so101_wsl.sh` | minimal WSL SO101 artifact download |
| `scripts/start_policy_wsl.sh` | constrained RTX 4060 policy launcher |
| `scripts/keep_wsl_g05_alive.sh` | keep bootstrap/monitor services alive |
| `a1z_g05/monitor.py` | read-only deployment status page |
| `scripts/probe_orbbec_windows.py` | native Windows Orbbec/DirectShow probe |

## Tests

```bash
PYTHONPATH=. python -m pytest -q
```

The tests cover action dimensionality, NaN rejection, joint limits, the
official gripper convention, camera orientation, stale-camera rejection,
E-stop forwarding, shadow-mode no-write behavior, daemon singleton locking,
locked J4 ownership and stream safety.
