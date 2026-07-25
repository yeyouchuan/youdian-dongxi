# A1Z offline simulation workspace

This directory is deliberately isolated from the hardware-control scripts. The
tools here do not open CAN or serial devices.

## Runtime

Run `../bootstrap.sh` from the `robot-arm/` directory. The resulting `.venv`
contains:

- MuJoCo 3.5.0 (native Apple Silicon)
- Pinocchio 3.8.0
- the editable Galaxea A1Z `gripper` SDK

Downloaded first-party assets are kept under the ignored
`simulation/vendor/` directory:

- `galaxea-urdf`: sparse checkout of the official A1Z/G1Z URDF and STL meshes
- `galaxea-isaac-tutorial`: official Galaxea A1/G1 Isaac Sim USD examples

## Offline verification

Prepare a MuJoCo-compatible copy of the model:

```bash
.venv/bin/python simulation/prepare_a1z_mujoco.py
```

Run FK/IK and simulator smoke tests:

```bash
.venv/bin/python simulation/a1z_offline_smoke.py
```

Preview the simulation-only hackathon pose candidates and validate their
minimum-jerk trajectory:

```bash
.venv/bin/python simulation/a1z_demo_trajectory.py
```

The generated contact sheet is written to
`simulation/artifacts/a1z_demo_pose_candidates.jpg`. These poses are
simulation candidates only and are not approved hardware commands.
`AIR_PICK_PRE` represents the requested high, empty-space grasp rehearsal; the
current vendor model has fixed gripper fingers, so open/close is an annotated
event rather than simulated finger motion.

The generated model is written to `simulation/generated/a1z_g1z/` and is not
intended to replace the vendor URDF.

## Safety boundary

Simulation code must output bounded candidate joint trajectories only. A
separate hardware gate must check timestamps, workspace constraints, collision
clearance, joint position/velocity/acceleration limits, and operator enable
before any candidate can reach the real robot.
