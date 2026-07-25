#!/usr/bin/env python3
"""Low-speed, empty-workspace A1Z coordinated waypoint test.

This is a hardware runner. It does not close the gripper or perform contact.
It starts from the measured run baseline, visits simulation-reviewed poses,
returns through bounded waypoints, and separately homes to zero before the
operator-supported disable interlock.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from typing import Any

import numpy as np

from scripts.a1z_hhs_transport import open_hhs_bus
from scripts.a1z_safe_shutdown import home_support_then_stop, support_then_stop
from scripts.a1z_six_axis_test import (
    DEFAULT_KD,
    DEFAULT_KP,
    SOFT_LIMITS,
    STARTUP_KD,
    STARTUP_KP,
    configure_motor_b_mit_mode,
    create_robot,
    prime_feedback,
    validate_pose,
    wait_for_fresh_feedback,
)
from simulation.a1z_demo_trajectory import POSES_DEG

MAX_SEGMENT_RAD = np.radians(35.0)
POSE_MARGIN_RAD = 0.08
MAX_TEMP_C = 60.0
TRACKING_MIN_RATIO = 0.30
TRACKING_MAX_OVERSHOOT_RAD = np.radians(10.0)
TRACKING_IGNORE_RAD = np.radians(3.0)
BASELINE_TOLERANCE_RAD = np.radians(5.0)
ADAPTIVE_STEP_RAD = np.radians(20.0)
STAGE_NAMES = ("WAKE_LOOK", "AIR_PICK_PRE", "LIFT", "WAKE_LOOK")


def strict_validate_target(name: str, target: np.ndarray) -> None:
    """Require a finite pose with margin inside every physical limit."""
    validate_pose(target, tolerance=0.0)
    invalid = (target < SOFT_LIMITS[:, 0] + POSE_MARGIN_RAD) | (
        target > SOFT_LIMITS[:, 1] - POSE_MARGIN_RAD
    )
    if np.any(invalid):
        joints = (np.flatnonzero(invalid) + 1).tolist()
        raise ValueError(f"{name}: insufficient limit margin at joints {joints}")


def validate_segment(start: np.ndarray, target: np.ndarray) -> None:
    """Reject a coordinated segment with any joint jump over 35 degrees."""
    jumps = np.abs(target - start)
    if np.any(jumps > MAX_SEGMENT_RAD):
        joints = (np.flatnonzero(jumps > MAX_SEGMENT_RAD) + 1).tolist()
        raise ValueError(f"segment exceeds 35 deg at joints {joints}")


def tracking_passed(
    start: np.ndarray, target: np.ndarray, measured: np.ndarray
) -> bool:
    """Require every materially commanded axis to move in the right direction."""
    command = target - start
    actual = measured - start
    active = np.abs(command) >= TRACKING_IGNORE_RAD
    if not np.any(active):
        return True
    ratios = np.abs(actual[active] / command[active])
    overshoot = np.maximum(
        np.abs(actual[active]) - np.abs(command[active]),
        0.0,
    )
    return bool(
        np.all(np.sign(actual[active]) == np.sign(command[active]))
        and np.all(ratios >= TRACKING_MIN_RATIO)
        and np.all(overshoot <= TRACKING_MAX_OVERSHOOT_RAD)
    )


def tracking_ratios(
    start: np.ndarray, target: np.ndarray, measured: np.ndarray
) -> np.ndarray:
    """Return signed measured/commanded progress for materially moved joints."""
    command = target - start
    actual = measured - start
    ratios = np.full(command.shape, np.nan, dtype=np.float64)
    active = np.abs(command) >= TRACKING_IGNORE_RAD
    ratios[active] = actual[active] / command[active]
    return ratios


def target_reached(
    target: np.ndarray,
    measured: np.ndarray,
    tolerance: float = BASELINE_TOLERANCE_RAD,
) -> bool:
    """Return whether every measured joint is inside the goal tolerance."""
    return bool(
        np.all(np.isfinite(measured))
        and np.max(np.abs(measured - target)) <= tolerance
    )


def check_live_state(robot: Any) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Validate current feedback, temperature, and control-loop health."""
    if not robot.is_running:
        raise RuntimeError("control loop stopped")
    pose = robot.get_joint_pos()[:6]
    validate_pose(pose)
    state = robot.get_joint_state()
    if np.any(~np.isfinite(state["temp_mos"])):
        raise RuntimeError("non-finite motor temperature")
    if np.any(state["temp_mos"] > MAX_TEMP_C):
        raise RuntimeError(
            f"MOS temperature exceeded {MAX_TEMP_C:.0f} C: "
            f"{state['temp_mos'].round(1).tolist()}"
        )
    return pose, state


def move_and_verify(
    robot: Any,
    name: str,
    target: np.ndarray,
    speed: float,
    abort: threading.Event,
    require_margin: bool = True,
    kp: np.ndarray | None = None,
    kd: np.ndarray | None = None,
) -> np.ndarray:
    """Execute one bounded waypoint and require measured coordinated progress."""
    start, _ = check_live_state(robot)
    if require_margin:
        strict_validate_target(name, target)
    else:
        validate_pose(target)
    validate_segment(start, target)
    if abort.is_set():
        raise RuntimeError("aborted before waypoint")

    logging.info(
        "%s start=%s target=%s deg",
        name,
        np.degrees(start).round(2).tolist(),
        np.degrees(target).round(2).tolist(),
    )
    # Previous stages may have left a large PD tracking error. Rebase the
    # command on the measured pose before constructing the next interpolation,
    # otherwise the SDK starts from its stale commanded target.
    robot.command_joint_pos(start)
    time.sleep(0.15)
    robot.move_joints(
        target,
        speed=speed,
        kp=DEFAULT_KP if kp is None else kp,
        kd=DEFAULT_KD if kd is None else kd,
        max_jump_rad=MAX_SEGMENT_RAD,
    )

    deadline = time.monotonic() + 4.0
    measured = start
    state: dict[str, np.ndarray] | None = None
    while time.monotonic() < deadline:
        if abort.is_set():
            raise RuntimeError("aborted while verifying waypoint")
        measured, state = check_live_state(robot)
        if tracking_passed(start, target, measured):
            break
        time.sleep(0.05)
    if state is None or not tracking_passed(start, target, measured):
        ratios = tracking_ratios(start, target, measured)
        if state is not None and target_reached(target, measured):
            logging.info(
                "%s accepted inside %.1f deg goal tolerance; "
                "tracking ratios=%s",
                name,
                np.degrees(BASELINE_TOLERANCE_RAD),
                np.round(ratios, 3).tolist(),
            )
            return measured
        effort = None if state is None else state["eff"].round(2).tolist()
        temperatures = (
            None if state is None else state["temp_mos"].round(1).tolist()
        )
        logging.error(
            "%s tracking failed: ratios=%s effort=%s Nm temp=%s C",
            name,
            np.round(ratios, 3).tolist(),
            effort,
            temperatures,
        )
        raise RuntimeError(
            f"{name}: measured coordinated progress did not pass; "
            f"pose={np.degrees(measured).round(2).tolist()} deg"
        )
    logging.info(
        "%s measured=%s deg effort=%s Nm temp=%s C status=%s",
        name,
        np.degrees(measured).round(2).tolist(),
        state["eff"].round(2).tolist(),
        state["temp_mos"].round(1).tolist(),
        state["error_codes"].astype(int).tolist(),
    )
    return measured


def move_toward_goal(
    robot: Any,
    name: str,
    goal: np.ndarray,
    speed: float,
    abort: threading.Event,
    attempts: int = 8,
    require_margin: bool = True,
    kp: np.ndarray | None = None,
    kd: np.ndarray | None = None,
    speed_limit: float = 0.06,
) -> bool:
    """Replan bounded measured-pose steps until a goal is physically reached."""
    if abort.is_set() or not robot.is_running:
        return False
    if require_margin:
        strict_validate_target(name, goal)
    else:
        validate_pose(goal)
    for index in range(1, attempts + 1):
        current, _ = check_live_state(robot)
        delta = goal - current
        if np.max(np.abs(delta)) <= BASELINE_TOLERANCE_RAD:
            return True
        scale = min(1.0, ADAPTIVE_STEP_RAD / np.max(np.abs(delta)))
        target = current + scale * delta
        move_and_verify(
            robot,
            f"{name}_{index}",
            target,
            min(speed, speed_limit),
            abort,
            require_margin=require_margin,
            kp=kp,
            kd=kd,
        )
    current, _ = check_live_state(robot)
    return bool(
        np.max(np.abs(current - goal)) <= BASELINE_TOLERANCE_RAD
    )


def run(
    speed: float,
    gravity_factor: float,
    recovery_baseline: np.ndarray | None = None,
    stage_names: tuple[str, ...] = STAGE_NAMES,
) -> None:
    """Run the coordinated empty-workspace trajectory."""
    bus = open_hhs_bus()
    robot = create_robot(bus, gravity_factor)
    abort = threading.Event()
    started = False
    baseline: np.ndarray | None = None
    safe_return_confirmed = False

    def handle_signal(signum: int, _frame: Any) -> None:
        logging.warning("Signal %s: requesting synchronous zero homing", signum)
        abort.set()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        configure_motor_b_mit_mode(robot)
        primed_pose, primed_feedback = prime_feedback(robot, bus, abort)
        logging.info("Primed pose: %s deg", np.degrees(primed_pose).round(2))
        robot.start(initial_kp=STARTUP_KP, initial_kd=STARTUP_KD)
        started = True
        wait_for_fresh_feedback(robot, primed_feedback, abort)
        time.sleep(0.8)
        running_pose, initial_state = check_live_state(robot)
        if np.max(np.abs(running_pose - primed_pose)) > 0.15:
            raise RuntimeError("zero-gain startup pose diverged from primed pose")
        robot.command_joint_pos(running_pose)
        time.sleep(0.5)
        measured_baseline, initial_state = check_live_state(robot)
        baseline = (
            recovery_baseline.copy()
            if recovery_baseline is not None
            else measured_baseline.copy()
        )
        validate_pose(baseline)
        logging.info(
            "Measured start=%s deg return baseline=%s deg temp=%s C status=%s",
            np.degrees(measured_baseline).round(2).tolist(),
            np.degrees(baseline).round(2).tolist(),
            initial_state["temp_mos"].round(1).tolist(),
            initial_state["error_codes"].astype(int).tolist(),
        )

        if recovery_baseline is not None:
            if not move_toward_goal(
                robot,
                "RECOVERY_BASELINE",
                baseline,
                speed,
                abort,
                require_margin=False,
            ):
                raise RuntimeError("recovery baseline did not converge")
            safe_return_confirmed = True
            logging.info("Recovery baseline reached")
            return

        targets = [
            (name, np.radians(POSES_DEG[name])) for name in stage_names
        ]
        for name, target in targets:
            if not move_toward_goal(robot, name, target, speed, abort):
                raise RuntimeError(f"{name} did not converge")
        if not move_toward_goal(
            robot,
            "BASELINE",
            baseline,
            min(speed, 0.06),
            abort,
            require_margin=False,
        ):
            raise RuntimeError("final baseline did not converge")
        safe_return_confirmed = True

        final_pose, final_state = check_live_state(robot)
        offsets = np.degrees(final_pose - baseline)
        if np.any(np.abs(final_pose - baseline) > BASELINE_TOLERANCE_RAD):
            raise RuntimeError(
                f"final baseline offset exceeded 5 deg: {offsets.round(2).tolist()}"
            )
        logging.info(
            "Coordinated test passed; baseline offsets=%s deg temp=%s C",
            offsets.round(2).tolist(),
            final_state["temp_mos"].round(1).tolist(),
        )
    finally:
        if started:
            if (
                baseline is not None
                and not safe_return_confirmed
                and not abort.is_set()
                and robot.is_running
            ):
                try:
                    safe_return_confirmed = move_toward_goal(
                        robot,
                        "RECOVERY_BASELINE",
                        baseline,
                        min(speed, 0.05),
                        abort,
                        require_margin=False,
                    )
                except Exception:
                    logging.exception("Automatic safe-baseline return failed")
            if not safe_return_confirmed:
                logging.error("Run baseline was not confirmed before homing")
            home_support_then_stop(robot)
        else:
            support_then_stop(robot)
        bus.shutdown()
        logging.info("All arm motors disabled")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speed", type=float, default=0.06)
    parser.add_argument("--gravity-factor", type=float, default=0.20)
    parser.add_argument("--confirm-clear", action="store_true")
    parser.add_argument(
        "--recover-baseline-deg",
        type=str,
        help="comma-separated six-joint run baseline; return-only stage",
    )
    parser.add_argument(
        "--stages",
        default=",".join(STAGE_NAMES),
        help="comma-separated simulation-reviewed pose names",
    )
    args = parser.parse_args()
    if not args.confirm_clear:
        parser.error("--confirm-clear is required for active motion")
    if not 0 < args.speed <= 0.08:
        parser.error("--speed must be in (0, 0.08] rad/s")
    if not 0 <= args.gravity_factor <= 0.30:
        parser.error("--gravity-factor must be in [0, 0.30]")
    recovery_baseline = None
    if args.recover_baseline_deg:
        try:
            values = [
                float(value)
                for value in args.recover_baseline_deg.split(",")
            ]
        except ValueError:
            parser.error("--recover-baseline-deg must contain six numbers")
        if len(values) != 6:
            parser.error("--recover-baseline-deg must contain six numbers")
        recovery_baseline = np.radians(values)
    stage_names = tuple(
        value.strip() for value in args.stages.split(",") if value.strip()
    )
    unknown_stages = [name for name in stage_names if name not in POSES_DEG]
    if not stage_names:
        parser.error("--stages must contain at least one pose name")
    if unknown_stages:
        parser.error(f"unknown --stages values: {unknown_stages}")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run(
        args.speed,
        args.gravity_factor,
        recovery_baseline,
        stage_names,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
