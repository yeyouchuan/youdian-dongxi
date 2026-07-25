#!/usr/bin/env python3
"""Build and preview offline A1Z hackathon-demo pose candidates.

This module is deliberately simulation-only. It imports no CAN, USB-CAN, or
serial transport and cannot command the real robot.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import mujoco
import numpy as np

try:
    from simulation.prepare_a1z_mujoco import DEFAULT_OUTPUT, prepare_model
except ModuleNotFoundError:
    from prepare_a1z_mujoco import DEFAULT_OUTPUT, prepare_model

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = REPO_ROOT / "simulation/artifacts"
STRICT_LIMITS = np.array(
    [
        [-2.094, 2.094],
        [0.0, 3.142],
        [-3.142, 0.0],
        [-1.309, 1.309],
        [-1.484, 1.484],
        [-2.007, 2.007],
    ],
    dtype=np.float64,
)

# These are candidate poses for simulation review, not approved hardware
# commands. HOME_SAFE is based on the compact measured hardware pose; the
# others deliberately retain generous limit margins.
POSES_DEG: dict[str, np.ndarray] = {
    "HOME_SAFE": np.array([-2.0, 8.0, -10.0, 34.0, 0.0, -82.0]),
    "WAKE_LOOK": np.array([0.0, 24.0, -36.0, 24.0, 0.0, -65.0]),
    "AIR_PICK_PRE": np.array([0.0, 42.0, -68.0, 28.0, 0.0, -78.0]),
    "LIFT": np.array([0.0, 34.0, -52.0, 22.0, 0.0, -72.0]),
    "OFFER": np.array([16.0, 28.0, -44.0, 18.0, -8.0, -62.0]),
}

DEMO_SEQUENCE = (
    "HOME_SAFE",
    "WAKE_LOOK",
    "AIR_PICK_PRE",
    "LIFT",
    "OFFER",
    "LIFT",
    "HOME_SAFE",
)


@dataclass(frozen=True)
class Trajectory:
    positions: np.ndarray
    velocities: np.ndarray
    pose_boundaries: tuple[tuple[str, int], ...]
    sample_hz: float


def validate_pose(name: str, pose: np.ndarray, margin_rad: float = 0.08) -> None:
    """Require a finite six-joint pose with strict physical-limit margin."""
    if pose.shape != (6,) or not np.all(np.isfinite(pose)):
        raise ValueError(f"{name}: expected six finite joints")
    below = pose < STRICT_LIMITS[:, 0] + margin_rad
    above = pose > STRICT_LIMITS[:, 1] - margin_rad
    if np.any(below | above):
        joints = (np.flatnonzero(below | above) + 1).tolist()
        raise ValueError(f"{name}: insufficient limit margin at joints {joints}")


def minimum_jerk_segment(
    start: np.ndarray,
    end: np.ndarray,
    max_speed_rad_s: float,
    sample_hz: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate a bounded minimum-jerk joint-space segment."""
    if max_speed_rad_s <= 0 or sample_hz <= 0:
        raise ValueError("speed and sample rate must be positive")
    delta = end - start
    max_distance = float(np.max(np.abs(delta)))
    # Peak minimum-jerk speed is 1.875 times average speed.
    duration = max(0.5, 1.875 * max_distance / max_speed_rad_s)
    steps = max(2, int(np.ceil(duration * sample_hz)) + 1)
    t = np.linspace(0.0, 1.0, steps)
    alpha = 10 * t**3 - 15 * t**4 + 6 * t**5
    alpha_dot = (30 * t**2 - 60 * t**3 + 30 * t**4) / duration
    positions = start[None, :] + alpha[:, None] * delta[None, :]
    velocities = alpha_dot[:, None] * delta[None, :]
    return positions, velocities


def build_demo_trajectory(
    max_speed_rad_s: float = 0.12,
    sample_hz: float = 50.0,
) -> Trajectory:
    """Build the complete candidate demo sequence with validation."""
    poses = {name: np.radians(values) for name, values in POSES_DEG.items()}
    for name, pose in poses.items():
        validate_pose(name, pose)

    position_parts: list[np.ndarray] = []
    velocity_parts: list[np.ndarray] = []
    boundaries: list[tuple[str, int]] = [(DEMO_SEQUENCE[0], 0)]
    sample_index = 0
    for start_name, end_name in zip(DEMO_SEQUENCE, DEMO_SEQUENCE[1:]):
        positions, velocities = minimum_jerk_segment(
            poses[start_name],
            poses[end_name],
            max_speed_rad_s=max_speed_rad_s,
            sample_hz=sample_hz,
        )
        if position_parts:
            positions = positions[1:]
            velocities = velocities[1:]
        position_parts.append(positions)
        velocity_parts.append(velocities)
        sample_index += len(positions)
        boundaries.append((end_name, sample_index - 1))

    all_positions = np.vstack(position_parts)
    all_velocities = np.vstack(velocity_parts)
    for index, pose in enumerate(all_positions):
        validate_pose(f"trajectory[{index}]", pose)
    if float(np.max(np.abs(all_velocities))) > max_speed_rad_s + 1e-9:
        raise RuntimeError("generated trajectory exceeds speed bound")
    return Trajectory(
        positions=all_positions,
        velocities=all_velocities,
        pose_boundaries=tuple(boundaries),
        sample_hz=sample_hz,
    )


def load_model() -> mujoco.MjModel:
    """Load the prepared official model, creating it when necessary."""
    model_path = DEFAULT_OUTPUT / "A1Z_G1Z.urdf"
    if not model_path.is_file():
        model_path = prepare_model(
            source=(
                REPO_ROOT
                / "simulation/vendor/galaxea-urdf/A1Z/A1Z_G1Z"
            ),
            output=DEFAULT_OUTPUT,
        )
    return mujoco.MjModel.from_xml_path(str(model_path))


def tool_position(model: mujoco.MjModel, pose: np.ndarray) -> np.ndarray:
    """Return arm_link6 origin in the MuJoCo world frame."""
    data = mujoco.MjData(model)
    data.qpos[:] = pose
    mujoco.mj_forward(model, data)
    body_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_BODY, "arm_link6"
    )
    return data.xpos[body_id].copy()


def render_pose_sheet(
    model: mujoco.MjModel,
    output: Path,
    width: int = 480,
    height: int = 360,
) -> Path:
    """Render a labeled contact sheet of the unique named poses."""
    renderer = mujoco.Renderer(model, height=height, width=width)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:] = np.array([0.0, 0.0, 0.18])
    camera.distance = 0.9
    camera.azimuth = 135.0
    camera.elevation = -18.0

    panels: list[np.ndarray] = []
    for name, pose_deg in POSES_DEG.items():
        data = mujoco.MjData(model)
        data.qpos[:] = np.radians(pose_deg)
        mujoco.mj_forward(model, data)
        renderer.update_scene(data, camera=camera)
        rgb = renderer.render().copy()
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        cv2.putText(
            bgr,
            name,
            (18, 34),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (20, 20, 20),
            4,
            cv2.LINE_AA,
        )
        cv2.putText(
            bgr,
            name,
            (18, 34),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        panels.append(bgr)
    renderer.close()

    blank = np.full_like(panels[0], 245)
    while len(panels) < 6:
        panels.append(blank)
    rows = [np.hstack(panels[index : index + 3]) for index in (0, 3)]
    sheet = np.vstack(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet):
        raise RuntimeError(f"failed to write {output}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speed", type=float, default=0.12)
    parser.add_argument("--sample-hz", type=float, default=50.0)
    parser.add_argument(
        "--render",
        type=Path,
        default=ARTIFACT_DIR / "a1z_demo_pose_candidates.jpg",
    )
    args = parser.parse_args()

    trajectory = build_demo_trajectory(args.speed, args.sample_hz)
    model = load_model()
    print(
        f"trajectory samples={len(trajectory.positions)}, "
        f"duration={(len(trajectory.positions) - 1) / trajectory.sample_hz:.2f}s, "
        f"peak_speed={np.max(np.abs(trajectory.velocities)):.4f} rad/s"
    )
    for name, pose_deg in POSES_DEG.items():
        position = tool_position(model, np.radians(pose_deg))
        print(
            f"{name:10s} q_deg={pose_deg.tolist()} "
            f"arm_link6_xyz={position.round(4).tolist()} m"
        )
    output = render_pose_sheet(model, args.render.resolve())
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
