# Hardware scripts

Run every command from `robot-arm/` with `PYTHONPATH=.`.

## Active hardware runners

- `a1z_safe_teach_and_play.py`: arm + gripper teaching, raw preservation,
  offline smoothing, validated replay, and supported shutdown.
- `a1z_safe_dance.py`: official `dance.py` choreography through continuous
  six-axis moves and safety gates.
- `a1z_safe_gripper_free_test.py`: gripper-only close/half/open test; never
  enables J1–J6.
- `a1z_six_axis_test.py`: selected individual-joint diagnostics.
- `a1z_coordinated_demo_test.py`: bounded coordinated waypoint diagnostics.

## Shared safety and transport

- `a1z_hhs_transport.py`: macOS HHS USB-CANFD compatibility and TX echo
  filtering.
- `a1z_hhs_probe.py`: descriptor-only/passive CAN probe; no motor enable.
- `a1z_safe_shutdown.py`: compact/zero parking and exact
  `PARKED_SUPPORTED` interlock.

All active runners require explicit `--confirm-clear`. Ctrl+C requests guarded
parking; it must not be replaced with immediate process termination. If the
control loop or power is already lost, software cannot park the arm—support it
physically at once.

See the parent [README](../README.md) for commands and
[hardware log](../docs/a1z-test-log-2026-07-23.md) for observed failures.
