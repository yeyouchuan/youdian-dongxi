# Robot Arm

One workspace for the Galaxea A1Z hardware runners, G0.5 policy bridge,
official SDK checkout, recorded trajectories, simulation, tests, and
SmartCushion frontend.

## Layout

```text
robot-arm/
├── a1z-g05-client/            # DGX G0.5 ↔ Mark A1Z bridge and safe daemon
├── cushion-reminder-service/  # MQTT simulator and local scenario trigger API
├── GALAXEA-A1Z/               # nested pinned SDK checkout used on the robot
├── scripts/                    # macOS HHS transport and guarded hardware runners
├── tests/                      # offline safety/regression tests
├── recordings/a1z_teach/      # real teach trajectories and smoothed derivatives
├── simulation/                 # offline FK/IK, dynamics, and MuJoCo tools
├── frontend/cushion-dashboard/ # web frontend
├── firmware/                   # reserved for ESP32 and embedded modules
├── docs/                       # runbooks, technical summaries and service plans
├── bootstrap.sh               # pinned SDK + Python environment setup
└── requirements-macos.txt
```

`GALAXEA-A1Z/` is a nested Git checkout and `.venv/` is local. Run the
bootstrap script to recreate the tested upstream base. The deployed robot
checkout additionally contains the power-cycle encoder-turn recovery described
below. An existing local `dimos/` checkout is not required by the current
runners or G0.5 path.

## What is useful now

| Area | Status | Start here |
| --- | --- | --- |
| G0.5 → real A1Z | Working with safety limits; semantic grasping remains experimental | [`a1z-g05-client/README.md`](a1z-g05-client/README.md) |
| G0.5/A1Z technical design | Current topology, mapping, camera and safety contract | [`docs/g05-a1z-technical-summary.md`](docs/g05-a1z-technical-summary.md) |
| MQTT SmartCushion service | Local simulator/API working; production receiver planned | [`cushion-reminder-service/README.md`](cushion-reminder-service/README.md) |
| OpenAI action evaluator | Designed, not implemented | [`docs/openai-action-evaluator-workflow.md`](docs/openai-action-evaluator-workflow.md) |
| SmartCushion Demo | Product behavior and staged acceptance | [`docs/smart-cushion-a1z-hackathon-demo.md`](docs/smart-cushion-a1z-hackathon-demo.md) |
| macOS direct hardware runners | Working guarded wrappers | [`scripts/README.md`](scripts/README.md) |
| Simulation | Offline FK/IK/dynamics and MuJoCo | [`simulation/README.md`](simulation/README.md) |
| Frontend | Static SmartCushion report Demo | [`frontend/cushion-dashboard/README.md`](frontend/cushion-dashboard/README.md) |
| Historical evidence | Failures, measurements and mitigations | [`docs/a1z-test-log-2026-07-23.md`](docs/a1z-test-log-2026-07-23.md) |

## Current validated G0.5 deployment

As of 2026-07-24:

```text
mark/WSL (A1Z + camera) -> Mac private relay -> DGX Spark G0.5
```

- DGX Spark runs the SO101 checkpoint on GB10 unified memory.
- Mark owns `can0`, `/dev/video0`, `/tmp/a1z.sock` and the real-time client.
- The A1Z safe daemon runs at 50 Hz with a 40 Hz floor and 350 ms stream
  watchdog.
- SO100 controls A1Z J1/J2/J3/J5/J6 plus the gripper; J4 is daemon-held.
- Camera input is corrected by a fixed 180° rotation.
- Power-cycle MotorA `±2π` encoder-turn changes are resolved in both feedback
  and outgoing motor commands.
- The stable physical neutral pose is approximately
  `(0, 60, -60, 0, 0, 0)` with the gripper open.

The current single-camera path is enough for integration tests, but official
SO100 deployment expects a real `exterior` camera plus `wrist_right`. Add the
fixed exterior camera before evaluating grasp success or building the MQTT
reminder service around semantic motion.

Local shadow test without moving the robot:

```bash
cd robot-arm/cushion-reminder-service
uv run cushion-web
```

Then open `http://127.0.0.1:3000`. See the service README before enabling the
explicit `ssh-mark` execution mode.

Useful robot-side commands:

```bash
cd ~/hardware/robot-arm/a1z-g05-client
bash scripts/start_a1z_safe_server.sh
bash scripts/preflight_mark.sh --operator-checked

PYTHONPATH=. ~/GALAXEA-A1Z/.venv/bin/python -m a1z_g05.headless \
  --config config.mark-execute.yaml \
  --task "Perform a small non-contact reminder gesture, then stop." \
  --max-steps 64
```

Do not use an open-ended “poke/tap the person” prompt. The current RGB-only
policy has no force/触觉 safety contract. Human reminders must remain
non-contact; contact testing is restricted to a fixed instrumented foam
fixture.

## Mandatory A1Z safety

The A1Z has no brake lock. Removing 24 V or disabling torque makes the arm
fall.

1. Fix the base securely and clear people, cables, and obstacles from the
   complete reachable workspace.
2. Connect 24 V, wait several seconds for drive initialization, and only then
   enable through software.
3. Keep an operator beside the PSU and physically support the arm whenever
   torque may be disabled.
4. Validate every joint-space or IK result against the official software
   limits before sending it.
5. Move distant targets through bounded interpolation; never send an
   unchecked far target.
6. The first gravity-compensation test must be at or below `0.30`. Confirm
   compensation acts upward before increasing it. This rig has subsequently
   validated `0.70`, but another robot must repeat the low-factor direction
   check.
7. During normal shutdown, never use `kill -9`, close the terminal, unplug
   power, or bypass the final support interlock. Let the program park and hold
   the arm, physically support it, then type exactly `PARKED_SUPPORTED`.
8. In an emergency, terminate motion and use the PSU switch if continued
   powered motion is more dangerous. Expect an immediate drop; only catch or
   support the arm when doing so does not put a person in its path.
9. Before every run, check CAN feedback, motor temperature, free joint motion,
   binding, cable strain, and abnormal sound.

Read the complete [macOS bring-up guide](docs/a1z-macos-bringup.md) and
[hardware test log](docs/a1z-test-log-2026-07-23.md) before enabling motors.
The log intentionally includes failed attempts and unsafe behaviors.

## Reproduce the environment

Requirements for the tested macOS/HHS path:

- macOS on Apple Silicon with Python 3.12 (the Pinocchio 3.8 wheel used here
  is not runtime-compatible with Python 3.13 on the tested machine)
- Git
- macOS HHS USB-CANFD adapter for these local hardware wrappers
- `libusb` (`brew install libusb` on macOS)

Install the tested interpreter with `brew install python@3.12`, or set
`PYTHON_BIN` to an existing Python 3.12 executable:

From the repository root:

```bash
cd robot-arm
PYTHON_BIN=/path/to/python3.12 ./bootstrap.sh
```

The script:

- clones `userguide-galaxea/GALAXEA-A1Z` from the required `gripper` branch;
- checks out commit `e931ecd0e25ad35df251097ba42921b3d2fa7224`;
- creates `.venv`;
- installs the pinned SDK, HHS USB dependencies, tests, and simulation tools.

Verify without moving hardware:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests
.venv/bin/ruff check scripts tests simulation/*.py
PYTHONPATH=. .venv/bin/python scripts/a1z_safe_dance.py --audit-only
```

## Official examples and safe wrappers

The pinned upstream files are:

- `GALAXEA-A1Z/examples/teach_and_play.py`
- `GALAXEA-A1Z/examples/dance.py`
- `GALAXEA-A1Z/examples/gripper_hybrid_test.py`

The official examples default to Linux SocketCAN and do not implement this
rig's operator-supported shutdown. On macOS, use the corresponding wrappers
below instead of invoking the official hardware examples directly:

| Official behavior | Local macOS runner |
| --- | --- |
| teach and replay | `scripts/a1z_safe_teach_and_play.py` |
| dance | `scripts/a1z_safe_dance.py` |
| gripper travel | `scripts/a1z_safe_gripper_free_test.py` |

The wrappers import or call the official choreography/SDK behavior while
adding HHS transport, startup feedback priming, limits, speed gates, signal
handling, compact parking, and the `PARKED_SUPPORTED` interlock.

### Native official examples on Linux

On a Linux SocketCAN machine, first follow the pinned upstream
[`README.md`](https://github.com/userguide-galaxea/GALAXEA-A1Z/blob/e931ecd0e25ad35df251097ba42921b3d2fa7224/README.md)
to bind the adapter and bring up `can0` at 1 Mbit/s. With the arm supported
and the upstream `gripper` checkout installed:

```bash
cd GALAXEA-A1Z
../.venv/bin/python examples/teach_and_play.py --can can0 record teach.json
../.venv/bin/python examples/teach_and_play.py --can can0 play teach.json --speed 0.5
../.venv/bin/python examples/dance.py --can can0 --speed 0.6
```

These are the unmodified official programs. They use gravity compensation
`1.0` and disable torque after returning to their zero pose without this
workspace's `PARKED_SUPPORTED` prompt. Do not use them as a first hardware
test: establish gravity direction at `0.30` or below, keep physical support
ready, and prefer the guarded wrappers whenever using this HHS/macOS rig.

## Teach and play

Record:

```bash
PYTHONPATH=. .venv/bin/python scripts/a1z_safe_teach_and_play.py \
  record my_teach.json \
  --sample-hz 50 \
  --speed 0.50 \
  --gravity-factor 0.70 \
  --confirm-gravity-direction \
  --confirm-clear
```

Every recording first writes `recordings/a1z_teach/my_teach.raw.json`.
The normal `my_teach.json` is created only if limit and speed validation pass.

If CAN feedback produces discontinuous position steps, smooth it offline:

```bash
PYTHONPATH=. .venv/bin/python scripts/a1z_safe_teach_and_play.py \
  smooth my_teach.raw.json
```

This produces `my_teach.smoothed.json` without opening CAN. It preserves every
recorded endpoint and expands implausible steps into coordinated
minimum-jerk frames.

First playback:

```bash
PYTHONPATH=. .venv/bin/python scripts/a1z_safe_teach_and_play.py \
  play my_teach.smoothed.json \
  --speed 0.50 \
  --gravity-factor 0.70 \
  --confirm-gravity-direction \
  --confirm-clear
```

After a successful half-speed validation, `--speed 1.0` reproduces the
smoothed trajectory's original timing. Always complete a fresh preflight for
a newly recorded trajectory.

## Dance

Offline audit:

```bash
PYTHONPATH=. .venv/bin/python scripts/a1z_safe_dance.py --audit-only
```

Hardware run after the low-factor gravity direction has been established:

```bash
PYTHONPATH=. .venv/bin/python scripts/a1z_safe_dance.py \
  --gravity-factor 0.70 \
  --confirm-gravity-direction \
  --j2-kp 60 \
  --j3-kp 60 \
  --confirm-clear
```

The wrapper loads the official default order (`salute`, `wave`, `nod`,
`reach`, `bow`) and sends one continuous six-axis SDK trajectory per pose.
Do not run a full dance until home-only and the intended individual move have
passed on that powered session.

## Logs and known risks

- Full history: [docs/a1z-test-log-2026-07-23.md](docs/a1z-test-log-2026-07-23.md)
- macOS/HHS setup: [docs/a1z-macos-bringup.md](docs/a1z-macos-bringup.md)
- Teach recordings: [recordings/README.md](recordings/README.md)
- Script-specific safety: [scripts/README.md](scripts/README.md)
- Simulation boundary: [simulation/README.md](simulation/README.md)
- Frontend: [frontend/cushion-dashboard/README.md](frontend/cushion-dashboard/README.md)

Observed hazards include immediate drop after disable, stale or mixed-age CAN
feedback, TX echo starvation, startup position snaps before feedback priming,
joint-limit disagreement between an older URDF and the corrected SDK factory,
and visible stop/start motion caused by wrapper-level trajectory segmentation.
Do not remove a guard merely because one run succeeded.
