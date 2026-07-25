"""Shared A1Z zero-pose and operator-support shutdown interlock."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import numpy as np

ZERO_POSE = np.zeros(6, dtype=np.float64)
HOME_FRAMES = 60
HOME_FRAME_HZ = 60.0
ZERO_TOLERANCE_RAD = np.radians(5.0)
MEASURED_LIMIT_TOLERANCE_RAD = 0.03
ZERO_SETTLE_TIMEOUT_S = 5.0
SUPPORT_ACK = "PARKED_SUPPORTED"
PHYSICAL_LIMITS = np.array(
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


def minimum_jerk_pose_frames(
    start: np.ndarray,
    target: np.ndarray,
    frames: int = HOME_FRAMES,
) -> np.ndarray:
    """Return quintic minimum-jerk commands ending at a requested pose."""
    start = np.asarray(start, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if start.shape != (6,) or not np.all(np.isfinite(start)):
        raise ValueError("start must contain six finite joints")
    if target.shape != (6,) or not np.all(np.isfinite(target)):
        raise ValueError("target must contain six finite joints")
    if frames <= 0:
        raise ValueError("frames must be positive")
    t = np.arange(1, frames + 1, dtype=np.float64) / frames
    alpha = 10 * t**3 - 15 * t**4 + 6 * t**5
    commands = (
        start[None, :]
        + alpha[:, None] * (target - start)[None, :]
    )
    commands[-1] = target
    return commands


def minimum_jerk_zero_frames(
    start: np.ndarray,
    frames: int = HOME_FRAMES,
) -> np.ndarray:
    """Return exactly `frames` commands ending at joint-coordinate zero."""
    return minimum_jerk_pose_frames(start, ZERO_POSE, frames)


def animate_to_zero(
    robot: Any,
    *,
    target_pose: np.ndarray = ZERO_POSE,
    frames: int = HOME_FRAMES,
    frame_hz: float = HOME_FRAME_HZ,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    """Synchronously move to a shutdown pose while the robot remains enabled.

    This follows the official support example's 60-frame quintic interpolation.
    It deliberately does not call ``robot.stop()``.
    """
    if not robot.is_running:
        logging.error("Cannot home: control loop is not running")
        return False
    if frame_hz <= 0:
        raise ValueError("frame_hz must be positive")
    start = np.asarray(robot.get_joint_pos()[:6], dtype=np.float64)
    target_pose = np.asarray(target_pose, dtype=np.float64)
    if (
        start.shape != (6,)
        or not np.all(np.isfinite(start))
        or np.any(
            start < PHYSICAL_LIMITS[:, 0] - MEASURED_LIMIT_TOLERANCE_RAD
        )
        or np.any(
            start > PHYSICAL_LIMITS[:, 1] + MEASURED_LIMIT_TOLERANCE_RAD
        )
    ):
        logging.error("Cannot home from invalid measured pose: %s", start)
        return False
    if (
        target_pose.shape != (6,)
        or not np.all(np.isfinite(target_pose))
        or np.any(target_pose < PHYSICAL_LIMITS[:, 0])
        or np.any(target_pose > PHYSICAL_LIMITS[:, 1])
    ):
        logging.error("Invalid shutdown target pose: %s", target_pose)
        return False
    command_start = np.clip(
        start,
        PHYSICAL_LIMITS[:, 0],
        PHYSICAL_LIMITS[:, 1],
    )
    commands = minimum_jerk_pose_frames(command_start, target_pose, frames)
    logging.warning(
        "Moving to shutdown pose %s deg with %d-frame minimum jerk "
        "from %s deg",
        np.degrees(target_pose).round(2).tolist(),
        frames,
        np.degrees(start).round(2).tolist(),
    )
    period = 1.0 / frame_hz
    next_frame = monotonic()
    for command in commands:
        if not robot.is_running:
            logging.error("Control loop stopped during zero homing")
            return False
        robot.command_joint_pos(command)
        # command_joint_pos() in the current gripper-branch SDK does not clear
        # velocity/acceleration left by an interrupted move_joints(). Remove
        # those stale feedforward terms while retaining the SDK's validation.
        if hasattr(robot, "_command_lock") and hasattr(robot, "_command"):
            with robot._command_lock:
                robot._command.vel = ZERO_POSE.copy()
                robot._command.acc = ZERO_POSE.copy()
                robot._command.torque_ff = ZERO_POSE.copy()
        next_frame += period
        sleep(max(0.0, next_frame - monotonic()))

    deadline = monotonic() + ZERO_SETTLE_TIMEOUT_S
    measured = np.asarray(robot.get_joint_pos()[:6], dtype=np.float64)
    while (
        robot.is_running
        and np.max(np.abs(measured - target_pose)) > ZERO_TOLERANCE_RAD
        and monotonic() < deadline
    ):
        robot.command_joint_pos(target_pose)
        sleep(0.05)
        measured = np.asarray(robot.get_joint_pos()[:6], dtype=np.float64)
    converged = bool(
        robot.is_running
        and np.all(np.isfinite(measured))
        and np.max(np.abs(measured - target_pose)) <= ZERO_TOLERANCE_RAD
    )
    if converged:
        logging.warning(
            "Shutdown pose verified at %s deg; motors remain enabled",
            np.degrees(measured).round(2).tolist(),
        )
    else:
        logging.error(
            "Shutdown pose NOT verified; target=%s measured=%s deg",
            np.degrees(target_pose).round(2).tolist(),
            np.degrees(measured).round(2).tolist(),
        )
    return converged


def wait_for_operator_support(
    read_line: Callable[[str], str] = input,
) -> None:
    """Block until the nearby operator confirms physical support."""
    prompt = (
        "\nShutdown pose is still actively held. Confirm the arm is in its "
        "shutdown "
        "parking posture and physically support the no-brake arm now. "
        f"Type {SUPPORT_ACK} to permit motor disable: "
    )
    while True:
        try:
            response = read_line(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            logging.error(
                "Support acknowledgement missing; motor disable remains blocked"
            )
            continue
        if response == SUPPORT_ACK:
            return
        logging.warning("Exact acknowledgement %s is required", SUPPORT_ACK)


def support_then_stop(
    robot: Any,
    read_line: Callable[[str], str] = input,
) -> None:
    """Require physical support before disabling after a partial startup."""
    logging.warning(
        "Control startup did not complete; one or more motors may still be "
        "enabled. Physically support the arm before shutdown."
    )
    wait_for_operator_support(read_line)
    robot.stop()


def home_support_then_stop(
    robot: Any,
    read_line: Callable[[str], str] = input,
    *,
    parking_pose: np.ndarray = ZERO_POSE,
) -> bool:
    """Home if possible, require physical support, then disable motor torque."""
    homed = False
    while robot.is_running:
        try:
            homed = animate_to_zero(robot, target_pose=parking_pose)
            break
        except KeyboardInterrupt:
            logging.warning(
                "Interrupt received during shutdown; zero homing remains active"
            )
    wait_for_operator_support(read_line)
    robot.stop()
    return homed
