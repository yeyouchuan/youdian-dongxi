#!/usr/bin/env python3
"""Sequential, limit-checked Galaxea A1Z six-axis motion test on macOS.

This runner deliberately tests one joint at a time and returns it before
advancing. It requires a primed six-motor pose, zero-gain startup verification,
bounded minimum-jerk interpolation, and measured-displacement validation.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from typing import Any

import numpy as np

try:
    from scripts.a1z_hhs_transport import open_hhs_bus
    from scripts.a1z_safe_shutdown import home_support_then_stop, support_then_stop
except ModuleNotFoundError:
    from a1z_hhs_transport import open_hhs_bus
    from a1z_safe_shutdown import home_support_then_stop, support_then_stop

SOFT_LIMITS = np.array(
    [
        [-2.094, 2.094],
        [0.0, 3.142],
        [-3.142, 0.0],
        [-1.309, 1.309],
        [-1.484, 1.484],
        [-2.007, 2.007],
    ]
)
DEFAULT_KP = np.array([30.0, 30.0, 30.0, 30.0, 5.0, 5.0])
DEFAULT_KD = np.array([1.0, 1.0, 1.0, 0.5, 0.5, 0.5])
STARTUP_KP = np.zeros(6)
STARTUP_KD = np.array([0.5, 0.5, 0.5, 0.25, 0.25, 0.25])
LIMIT_MARGIN_RAD = 0.10
INITIAL_GRAVITY_FACTOR_MAX = 0.30
GRAVITY_FACTOR_MAX = 1.0


def validate_gravity_factor(
    factor: float,
    *,
    high_factor_direction_confirmed: bool,
) -> None:
    """Require a separate direction check before compensation above 0.30."""
    if not 0 <= factor <= GRAVITY_FACTOR_MAX:
        raise ValueError(
            f"gravity factor must be in [0, {GRAVITY_FACTOR_MAX:.1f}]"
        )
    if (
        factor > INITIAL_GRAVITY_FACTOR_MAX
        and not high_factor_direction_confirmed
    ):
        raise ValueError(
            "gravity factor above 0.30 requires confirmed compensation direction"
        )


def validate_pose(pose: np.ndarray, tolerance: float = 0.03) -> None:
    """Reject non-finite, wrong-sized, or out-of-limit joint poses."""
    if pose.shape != (6,) or not np.all(np.isfinite(pose)):
        raise ValueError("pose must contain six finite joint values")
    below = pose < SOFT_LIMITS[:, 0] - tolerance
    above = pose > SOFT_LIMITS[:, 1] + tolerance
    if np.any(below | above):
        offenders = np.flatnonzero(below | above) + 1
        raise ValueError(f"pose outside soft limits at joints {offenders.tolist()}")


def make_joint_targets(
    baseline: np.ndarray, amplitude_rad: float
) -> list[np.ndarray]:
    """Build one target per joint, moving toward that joint's limit midpoint."""
    validate_pose(baseline)
    if not 0 < amplitude_rad <= np.radians(30):
        raise ValueError("amplitude must be in (0, 30] degrees")
    midpoints = SOFT_LIMITS.mean(axis=1)
    targets: list[np.ndarray] = []
    for joint in range(6):
        direction = 1.0 if baseline[joint] <= midpoints[joint] else -1.0
        target = baseline.copy()
        target[joint] = np.clip(
            baseline[joint] + direction * amplitude_rad,
            SOFT_LIMITS[joint, 0] + LIMIT_MARGIN_RAD,
            SOFT_LIMITS[joint, 1] - LIMIT_MARGIN_RAD,
        )
        if abs(target[joint] - baseline[joint]) < amplitude_rad * 0.8:
            raise ValueError(f"joint {joint + 1} lacks margin for requested move")
        targets.append(target)
    return targets


def chain_motors(robot: Any) -> list[Any]:
    """Return the six vendor motor objects in CAN-ID order."""
    chain = robot._motor_chain
    return [*chain._motor_a_list, *chain._motor_b_list]


def feedback_snapshot(robot: Any) -> dict[int, Any]:
    """Retain the latest feedback object for each motor."""
    return {
        motor.motor_id: motor.last_feedback
        for motor in chain_motors(robot)
        if motor.last_feedback is not None
    }


def configure_motor_b_mit_mode(robot: Any) -> None:
    """Select MIT mode in RAM for J4-J6; the setting is lost on power cycle."""
    for motor in robot._motor_chain._motor_b_list:
        motor.set_ctrl_mode(1)


def prime_feedback(
    robot: Any,
    bus: Any,
    abort: threading.Event,
    timeout: float = 1.5,
) -> tuple[np.ndarray, dict[int, Any]]:
    """Collect real feedback for all six motors using zero position gain."""
    chain = robot._motor_chain
    zeros = np.zeros(6)
    probe_kd = np.full(6, 0.05)
    motors = chain_motors(robot)
    succeeded = False
    chain.enable_all()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if abort.is_set():
                raise RuntimeError("aborted during feedback priming")
            chain.send_commands(zeros, zeros, zeros, probe_kd, zeros)
            cycle_end = time.monotonic() + 0.04
            while time.monotonic() < cycle_end:
                chain.drain_and_update(
                    bus, timeout=0.005, max_messages=64
                )
                if all(motor.last_feedback is not None for motor in motors):
                    pose = chain.get_positions() * robot._joint_sign
                    validate_pose(pose)
                    succeeded = True
                    return pose.copy(), feedback_snapshot(robot)
                time.sleep(0.002)
        missing = [
            motor.motor_id
            for motor in motors
            if motor.last_feedback is None
        ]
        raise RuntimeError(f"feedback priming timeout; missing CAN IDs {missing}")
    finally:
        # On success, retain zero-gain motor enable through robot.start() so
        # the no-brake arm cannot sag between feedback priming and handoff.
        if not succeeded:
            chain.disable_all()


def wait_for_fresh_feedback(
    robot: Any,
    previous_feedback: dict[int, Any],
    abort: threading.Event,
    timeout: float = 1.0,
) -> None:
    """Require a new post-start reply from every motor before position hold."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if abort.is_set():
            raise RuntimeError("aborted during post-start feedback check")
        feedback = feedback_snapshot(robot)
        if len(feedback) == 6 and all(
            current is not previous_feedback.get(motor_id)
            for motor_id, current in feedback.items()
        ):
            return
        time.sleep(0.01)
    fresh = feedback_snapshot(robot)
    stale = [
        motor.motor_id
        for motor in chain_motors(robot)
        if (
            motor.motor_id not in fresh
            or fresh[motor.motor_id] is previous_feedback.get(motor.motor_id)
        )
    ]
    raise RuntimeError(f"no fresh post-start feedback from CAN IDs {stale}")


def create_robot(
    bus: Any,
    gravity_factor: float,
    default_kp: np.ndarray | None = None,
) -> Any:
    """Create the vendor robot with the already-opened HHS bus."""
    import can
    from a1z.robots.get_robot import get_a1z_robot

    real_bus_factory = can.interface.Bus
    can.interface.Bus = lambda *args, **kwargs: bus
    try:
        robot = get_a1z_robot(
            gravity_comp_factor=gravity_factor,
            zero_gravity_mode=False,
            control_freq_hz=100,
            min_freq_hz=45.0,
            default_kp=DEFAULT_KP if default_kp is None else default_kp,
            default_kd=DEFAULT_KD,
            with_gripper=False,
        )
        # The SDK factory currently uses ±1.484 rad for J4, but the bundled
        # A1Z_G1Z URDF specifies the stricter physical limit ±1.309 rad.
        robot._joint_limits = [tuple(limits) for limits in SOFT_LIMITS]
        return robot
    finally:
        can.interface.Bus = real_bus_factory


def measured_move_passed(
    baseline_value: float,
    target_value: float,
    measured_value: float,
) -> bool:
    """Require correct direction and bounded 65–135% command tracking."""
    commanded = target_value - baseline_value
    measured = measured_value - baseline_value
    if commanded == 0:
        return False
    ratio = abs(measured / commanded)
    return (
        np.sign(measured) == np.sign(commanded)
        and 0.65 <= ratio <= 1.35
    )


def wait_for_outbound_tracking(
    robot: Any,
    baseline: np.ndarray,
    target: np.ndarray,
    joint: int,
    abort: threading.Event,
    timeout: float = 3.0,
) -> np.ndarray:
    """Wait for slow loaded motion while enforcing direction and pose guards."""
    deadline = time.monotonic() + timeout
    commanded = target[joint] - baseline[joint]
    last_pose = robot.get_joint_pos()[:6]
    while time.monotonic() < deadline:
        if abort.is_set() or not robot.is_running:
            raise RuntimeError("test aborted or control loop stopped")
        last_pose = robot.get_joint_pos()[:6]
        validate_pose(last_pose)
        non_target_error = np.delete(np.abs(last_pose - baseline), joint)
        if np.any(non_target_error > np.radians(3)):
            offsets = np.degrees(last_pose - baseline).round(2).tolist()
            raise RuntimeError(
                f"J{joint + 1} move displaced another joint by >3 deg; "
                f"all offsets={offsets} deg"
            )
        measured = last_pose[joint] - baseline[joint]
        if abs(measured) > np.radians(0.5):
            if np.sign(measured) != np.sign(commanded):
                raise RuntimeError(f"J{joint + 1} moved in the wrong direction")
            if abs(measured / commanded) > 1.35:
                raise RuntimeError(f"J{joint + 1} exceeded 135% of command")
        if measured_move_passed(
            baseline[joint], target[joint], last_pose[joint]
        ):
            return last_pose
        time.sleep(0.05)
    return last_pose


def wait_for_return(
    robot: Any,
    baseline: np.ndarray,
    abort: threading.Event,
    timeout: float = 3.0,
) -> np.ndarray:
    """Wait for every axis to return within three degrees of baseline."""
    deadline = time.monotonic() + timeout
    last_pose = robot.get_joint_pos()[:6]
    while time.monotonic() < deadline:
        if abort.is_set() or not robot.is_running:
            raise RuntimeError("test aborted or control loop stopped")
        last_pose = robot.get_joint_pos()[:6]
        validate_pose(last_pose)
        if np.all(np.abs(last_pose - baseline) <= np.radians(3)):
            return last_pose
        time.sleep(0.05)
    return last_pose


def attempt_safe_baseline_return(
    robot: Any,
    baseline: np.ndarray,
    abort: threading.Event,
    speed: float,
    kp: np.ndarray | None = None,
) -> bool:
    """Return to the run baseline before the separate zero-homing phase."""
    if abort.is_set() or not robot.is_running:
        logging.warning(
            "Skipping automatic return: estop/abort or control loop stopped"
        )
        return False
    try:
        current = robot.get_joint_pos()[:6]
        validate_pose(current)
        if np.any(np.abs(current - baseline) > np.radians(3)):
            logging.warning("Returning to run baseline before zero homing")
            robot.move_joints(
                baseline,
                speed=min(speed, 0.06),
                kp=DEFAULT_KP if kp is None else kp,
                kd=DEFAULT_KD,
                max_jump_rad=np.radians(35),
            )
            returned = wait_for_return(robot, baseline, abort, timeout=5.0)
            if np.any(np.abs(returned - baseline) > np.radians(3)):
                logging.error(
                    "Safe baseline return did not converge; offsets=%s deg",
                    np.degrees(returned - baseline).round(2).tolist(),
                )
                return False
        logging.info(
            "Run baseline reached; official zero homing is still required"
        )
        return True
    except Exception:
        logging.exception("Automatic run-baseline return failed")
        return False


def run_test(
    amplitude_deg: float,
    speed: float,
    gravity_factor: float,
    joint_numbers: list[int] | None = None,
    preflight_only: bool = False,
    j3_kp: float = float(DEFAULT_KP[2]),
) -> None:
    """Run the active six-axis test. Caller must enforce operator confirmation."""
    bus = open_hhs_bus()
    test_kp = DEFAULT_KP.copy()
    test_kp[2] = j3_kp
    robot = create_robot(bus, gravity_factor, default_kp=test_kp)
    abort = threading.Event()
    started = False
    baseline: np.ndarray | None = None

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
        # Zero position gain prevents a snap even if startup feedback is late.
        robot.start(initial_kp=STARTUP_KP, initial_kd=STARTUP_KD)
        started = True
        wait_for_fresh_feedback(robot, primed_feedback, abort)
        time.sleep(0.8)
        if not robot.is_running:
            raise RuntimeError("control loop stopped during zero-gain startup")
        running_pose = robot.get_joint_pos()[:6]
        validate_pose(running_pose)
        if np.max(np.abs(running_pose - primed_pose)) > 0.15:
            raise RuntimeError("zero-gain startup pose diverged from primed pose")

        # Hold exactly the newly measured pose before any trajectory.
        robot.command_joint_pos(running_pose)
        time.sleep(0.5)
        baseline = robot.get_joint_pos()[:6]
        validate_pose(baseline)
        state = robot.get_joint_state()
        logging.info(
            "Preflight errors=%s effort=%s Nm temp_mos=%s C",
            state["error_codes"].astype(int).tolist(),
            state["eff"].round(2).tolist(),
            state["temp_mos"].round(1).tolist(),
        )
        if preflight_only:
            logging.info("Preflight-only check complete; no trajectory sent")
            return
        targets = make_joint_targets(baseline, np.radians(amplitude_deg))
        selected = joint_numbers or list(range(1, 7))

        for joint_number in selected:
            joint = joint_number - 1
            target = targets[joint]
            if abort.is_set() or not robot.is_running:
                raise RuntimeError("test aborted or control loop stopped")
            commanded = target[joint] - baseline[joint]
            logging.info(
                "J%d outbound %.2f deg", joint + 1, np.degrees(commanded)
            )
            robot.move_joints(
                target,
                speed=speed,
                kp=test_kp,
                kd=DEFAULT_KD,
                max_jump_rad=np.radians(amplitude_deg + 3),
            )
            reached = wait_for_outbound_tracking(
                robot, baseline, target, joint, abort
            )
            reached_state = robot.get_joint_state()
            logging.info(
                "J%d measured %.2f deg (requested %.2f deg); "
                "pose=%s deg effort=%s Nm errors=%s",
                joint + 1,
                np.degrees(reached[joint] - baseline[joint]),
                np.degrees(commanded),
                np.degrees(reached).round(2),
                reached_state["eff"].round(2).tolist(),
                reached_state["error_codes"].astype(int).tolist(),
            )
            if not measured_move_passed(
                baseline[joint], target[joint], reached[joint]
            ):
                raise RuntimeError(
                    f"J{joint + 1} displacement outside 65–135% command"
                )

            logging.info("J%d returning", joint + 1)
            robot.move_joints(
                baseline,
                speed=speed,
                kp=test_kp,
                kd=DEFAULT_KD,
                max_jump_rad=np.radians(amplitude_deg + 3),
            )
            returned = wait_for_return(robot, baseline, abort)
            if np.any(np.abs(returned - baseline) > np.radians(3)):
                raise RuntimeError(
                    f"J{joint + 1} return left an axis >3 deg from baseline"
                )
            logging.info("J%d passed", joint + 1)
    finally:
        if started:
            if baseline is not None:
                attempt_safe_baseline_return(
                    robot,
                    baseline,
                    abort,
                    speed,
                    kp=test_kp,
                )
            else:
                logging.warning(
                    "No validated run baseline; proceeding to guarded zero homing"
                )
            home_support_then_stop(robot)
        else:
            support_then_stop(robot)
        bus.shutdown()
        logging.info("All arm motors disabled")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amplitude-deg", type=float, default=5.0)
    parser.add_argument("--speed", type=float, default=0.10)
    parser.add_argument("--gravity-factor", type=float, default=0.20)
    parser.add_argument(
        "--confirm-gravity-direction",
        action="store_true",
        help="confirm <=0.30 testing showed compensation acts upward",
    )
    parser.add_argument("--j3-kp", type=float, default=float(DEFAULT_KP[2]))
    parser.add_argument(
        "--joints",
        type=str,
        default="1,2,3,4,5,6",
        help="comma-separated 1-based joints to test",
    )
    parser.add_argument(
        "--confirm-clear",
        action="store_true",
        help="confirm workspace clear, arm supported, operator at PSU",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="enable, verify fresh feedback/state, then stop without a trajectory",
    )
    args = parser.parse_args()
    if not args.confirm_clear:
        parser.error("--confirm-clear is required for active motion")
    if not 0 < args.amplitude_deg <= 30:
        parser.error("--amplitude-deg must be in (0, 30]")
    if not 0 < args.speed <= 0.20:
        parser.error("--speed must be in (0, 0.20] rad/s")
    try:
        validate_gravity_factor(
            args.gravity_factor,
            high_factor_direction_confirmed=args.confirm_gravity_direction,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if not DEFAULT_KP[2] <= args.j3_kp <= 60.0:
        parser.error("--j3-kp must be in [30, 60]")
    try:
        joints = [int(value) for value in args.joints.split(",")]
    except ValueError:
        parser.error("--joints must be comma-separated integers")
    if not joints or len(set(joints)) != len(joints) or any(
        joint < 1 or joint > 6 for joint in joints
    ):
        parser.error("--joints must contain unique values from 1 through 6")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run_test(
        args.amplitude_deg,
        args.speed,
        args.gravity_factor,
        joints,
        args.preflight_only,
        args.j3_kp,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
