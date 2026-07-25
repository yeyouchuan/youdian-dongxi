#!/usr/bin/env python3
"""Offline A1Z FK/IK and MuJoCo loading smoke test.

No robot transport modules are imported and no hardware device is opened.
"""

from __future__ import annotations

from pathlib import Path

import mujoco
import numpy as np

from prepare_a1z_mujoco import DEFAULT_OUTPUT, prepare_model

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_URDF = (
    REPO_ROOT
    / "GALAXEA-A1Z/a1z/robot_models/a1z/A1Z_G1Z.urdf"
)


def run_pinocchio_check() -> tuple[float, float]:
    from a1z.robots.kinematics import Kinematics

    kinematics = Kinematics(str(SDK_URDF), end_effector_frame="arm_link6")
    reference = np.array([0.1, 0.8, -1.0, 0.15, -0.2, 0.25])
    target = kinematics.fk(reference)
    initial = reference + np.array([0.02, -0.02, 0.02, 0.01, -0.01, 0.01])
    converged, solution = kinematics.ik(
        target,
        init_q=initial,
        frame_name="arm_link6",
        dt=0.1,
        max_iters=1000,
    )
    solved = kinematics.fk(solution, frame_name="arm_link6")
    position_error = float(np.linalg.norm(solved[:3, 3] - target[:3, 3]))
    rotation_error = float(np.linalg.norm(solved[:3, :3] - target[:3, :3]))
    within_limits = bool(
        np.all(solution >= kinematics._q_lower)
        and np.all(solution <= kinematics._q_upper)
    )
    if not converged or not within_limits:
        raise RuntimeError("Pinocchio IK failed or returned an invalid pose")
    return position_error, rotation_error


def run_pinocchio_dynamics_check() -> np.ndarray:
    from a1z.dynamics.gravity_model import GravityModel

    dynamics = GravityModel(str(SDK_URDF))
    q = np.array([0.1, 0.8, -1.0, 0.15, -0.2, 0.25])
    zero = np.zeros(6)
    gravity_torque = dynamics.compute_gravity_torque(q)
    inverse_dynamics = dynamics.compute_inverse_dynamics(q, zero, zero)
    if not np.all(np.isfinite(gravity_torque)):
        raise RuntimeError("Pinocchio returned non-finite gravity torque")
    if not np.allclose(gravity_torque, inverse_dynamics):
        raise RuntimeError("static RNEA result does not match gravity torque")
    return gravity_torque


def run_mujoco_check() -> tuple[int, int, float]:
    model_path = DEFAULT_OUTPUT / "A1Z_G1Z.urdf"
    if not model_path.is_file():
        model_path = prepare_model(
            source=(
                REPO_ROOT
                / "simulation/vendor/galaxea-urdf/A1Z/A1Z_G1Z"
            ),
            output=DEFAULT_OUTPUT,
        )
    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    for _ in range(100):
        mujoco.mj_step(model, data)
    return model.nq, model.nbody, float(data.time)


def main() -> int:
    position_error, rotation_error = run_pinocchio_check()
    gravity_torque = run_pinocchio_dynamics_check()
    nq, nbody, sim_time = run_mujoco_check()
    print(f"Pinocchio IK position error: {position_error:.8f} m")
    print(f"Pinocchio IK rotation-matrix error: {rotation_error:.8f}")
    print(f"Pinocchio gravity torque: {gravity_torque.round(6).tolist()} Nm")
    print(f"MuJoCo: nq={nq}, bodies={nbody}, simulated={sim_time:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
