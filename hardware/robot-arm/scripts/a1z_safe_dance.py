#!/usr/bin/env python3
"""Run the official A1Z dance choreography through macOS safety gates."""

from __future__ import annotations

import argparse
import importlib.util
import logging
import signal
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from scripts.a1z_coordinated_demo_test import (
    check_live_state,
    strict_validate_target,
    target_reached,
)
from scripts.a1z_hhs_transport import open_hhs_bus
from scripts.a1z_safe_shutdown import home_support_then_stop, support_then_stop
from scripts.a1z_six_axis_test import (
    DEFAULT_KP,
    STARTUP_KD,
    STARTUP_KP,
    configure_motor_b_mit_mode,
    create_robot,
    prime_feedback,
    validate_gravity_factor,
    validate_pose,
    wait_for_fresh_feedback,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_DANCE_PATH = REPO_ROOT / "GALAXEA-A1Z/examples/dance.py"
MAX_DANCE_BASE_SPEED_RAD_S = 0.60
MAX_DANCE_POSE_SPEED_RAD_S = 0.90
POSE_SETTLE_TIMEOUT_S = 4.0
MAX_DANCE_J2_KP = 60.0
MAX_DANCE_J3_KP = 60.0


def load_official_dance(path: Path = OFFICIAL_DANCE_PATH) -> ModuleType:
    """Load the pinned gripper-branch example without modifying vendor code."""
    spec = importlib.util.spec_from_file_location("galaxea_official_dance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load official dance example: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_choreography(module: ModuleType, order: tuple[str, ...]) -> None:
    """Validate every referenced official pose against strict physical limits."""
    unknown = [name for name in order if name not in module.MOVES]
    if unknown:
        raise ValueError(f"unknown official dance moves: {unknown}")
    referenced = {"home"}
    for move_name in order:
        referenced.update(
            pose_name for pose_name, _speed, _pause in module.MOVES[move_name]
        )
    for pose_name in sorted(referenced):
        strict_validate_target(pose_name, module.POSES[pose_name])


def build_dance_kp(j2_kp: float, j3_kp: float) -> np.ndarray:
    """Return per-joint gains tuned independently for loaded shoulder/elbow."""
    kp = DEFAULT_KP.copy()
    kp[1] = j2_kp
    kp[2] = j3_kp
    return kp


class SafetyGatedDanceRobot:
    """Expose the API expected by official Dance while gating every pose."""

    def __init__(
        self,
        robot: Any,
        abort: threading.Event,
        max_speed_rad_s: float,
        kp: np.ndarray,
    ) -> None:
        self._robot = robot
        self._abort = abort
        self._max_speed_rad_s = max_speed_rad_s
        self._kp = np.asarray(kp, dtype=np.float64)
        self.pose_names: dict[bytes, str] = {}

    def register_poses(self, poses: dict[str, np.ndarray]) -> None:
        self.pose_names = {
            np.asarray(pose, dtype=np.float64).tobytes(): name
            for name, pose in poses.items()
        }

    def move_joints(
        self,
        target: np.ndarray,
        speed: float,
        **_kwargs: Any,
    ) -> None:
        target = np.asarray(target, dtype=np.float64)
        name = self.pose_names.get(target.tobytes(), "official_pose")
        gated_speed = min(float(speed), self._max_speed_rad_s)
        logging.info(
            "Official dance pose=%s requested_speed=%.3f gated_speed=%.3f",
            name,
            speed,
            gated_speed,
        )
        strict_validate_target(f"DANCE_{name}", target)
        if self._abort.is_set():
            raise RuntimeError(f"official dance pose {name} aborted")
        start, _state = check_live_state(self._robot)
        logging.info(
            "DANCE_%s continuous start=%s target=%s deg",
            name,
            np.degrees(start).round(2).tolist(),
            np.degrees(target).round(2).tolist(),
        )
        self._robot.move_joints(
            target,
            speed=gated_speed,
            kp=self._kp,
        )

        deadline = time.monotonic() + POSE_SETTLE_TIMEOUT_S
        measured, state = check_live_state(self._robot)
        while not target_reached(target, measured):
            if self._abort.is_set():
                raise RuntimeError(f"official dance pose {name} aborted")
            if time.monotonic() >= deadline:
                error = np.degrees(measured - target).round(2).tolist()
                raise RuntimeError(
                    f"official dance pose {name} did not converge; "
                    f"error={error} deg"
                )
            time.sleep(0.05)
            measured, state = check_live_state(self._robot)
        logging.info(
            "DANCE_%s continuous measured=%s deg effort=%s Nm temp=%s C",
            name,
            np.degrees(measured).round(2).tolist(),
            state["eff"].round(2).tolist(),
            state["temp_mos"].round(1).tolist(),
        )

    def command_gripper(self, _value: float) -> None:
        raise RuntimeError("gripper commands are disabled in this dance run")


def shutdown_dance(robot: Any, official: ModuleType) -> bool:
    """Park at the official compact home pose before supported disable."""
    return home_support_then_stop(
        robot,
        parking_pose=np.asarray(official.POSES["home"], dtype=np.float64),
    )


def run(
    order: tuple[str, ...],
    base_speed: float,
    gravity_factor: float,
    j2_kp: float,
    j3_kp: float,
) -> None:
    """Run the full official choreography, then software-home before disable."""
    official = load_official_dance()
    validate_choreography(official, order)
    bus = open_hhs_bus()
    dance_kp = build_dance_kp(j2_kp, j3_kp)
    robot = create_robot(bus, gravity_factor, default_kp=dance_kp)
    abort = threading.Event()
    started = False

    def handle_signal(signum: int, _frame: Any) -> None:
        logging.warning("Signal %s: requesting automatic zero homing", signum)
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
        running_pose, state = check_live_state(robot)
        if np.max(np.abs(running_pose - primed_pose)) > 0.15:
            raise RuntimeError("zero-gain startup pose diverged from primed pose")
        robot.command_joint_pos(running_pose)
        time.sleep(0.5)
        running_pose, state = check_live_state(robot)
        validate_pose(running_pose)
        logging.info(
            "Dance preflight pose=%s deg temp=%s C status=%s",
            np.degrees(running_pose).round(2).tolist(),
            state["temp_mos"].round(1).tolist(),
            state["error_codes"].astype(int).tolist(),
        )

        gated = SafetyGatedDanceRobot(
            robot,
            abort,
            MAX_DANCE_POSE_SPEED_RAD_S,
            dance_kp,
        )
        gated.register_poses(official.POSES)
        dance = official.Dance(
            gated,
            base_speed=base_speed,
            with_gripper=False,
        )
        dance.run(list(order))
        logging.info("Official default dance choreography completed")
    finally:
        if started:
            shutdown_dance(robot, official)
        else:
            support_then_stop(robot)
        bus.shutdown()
        logging.info("All arm motors disabled")


def main() -> int:
    official = load_official_dance()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--moves",
        default=",".join(official.DEFAULT_ORDER),
        help="comma-separated official move names",
    )
    parser.add_argument("--speed", type=float, default=0.60)
    parser.add_argument("--gravity-factor", type=float, default=0.20)
    parser.add_argument(
        "--confirm-gravity-direction",
        action="store_true",
        help="confirm <=0.30 testing showed compensation acts upward",
    )
    parser.add_argument("--j2-kp", type=float, default=float(DEFAULT_KP[1]))
    parser.add_argument("--j3-kp", type=float, default=float(DEFAULT_KP[2]))
    parser.add_argument("--confirm-clear", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    order = tuple(value.strip() for value in args.moves.split(",") if value.strip())
    validate_choreography(official, order)
    if args.audit_only:
        print(
            f"official dance audit passed: moves={list(order)}, "
            f"poses={sorted(official.POSES)}"
        )
        return 0
    if not args.confirm_clear:
        parser.error("--confirm-clear is required for active motion")
    if not 0 < args.speed <= MAX_DANCE_BASE_SPEED_RAD_S:
        parser.error(
            f"--speed must be in "
            f"(0, {MAX_DANCE_BASE_SPEED_RAD_S:.2f}] rad/s"
        )
    try:
        validate_gravity_factor(
            args.gravity_factor,
            high_factor_direction_confirmed=args.confirm_gravity_direction,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if not DEFAULT_KP[1] <= args.j2_kp <= MAX_DANCE_J2_KP:
        parser.error(
            f"--j2-kp must be in [{DEFAULT_KP[1]:.0f}, "
            f"{MAX_DANCE_J2_KP:.0f}]"
        )
    if not DEFAULT_KP[2] <= args.j3_kp <= MAX_DANCE_J3_KP:
        parser.error(
            f"--j3-kp must be in [{DEFAULT_KP[2]:.0f}, "
            f"{MAX_DANCE_J3_KP:.0f}]"
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run(order, args.speed, args.gravity_factor, args.j2_kp, args.j3_kp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
