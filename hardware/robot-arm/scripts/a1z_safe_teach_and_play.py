#!/usr/bin/env python3
"""Safely teach and replay A1Z trajectories through the macOS HHS adapter.

This is a transport- and shutdown-safe wrapper around the official
``examples/teach_and_play.py`` behavior.  The recommended ``session`` command
records and replays without disabling the no-brake arm between those phases.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from scripts.a1z_hhs_transport import open_hhs_bus
from scripts.a1z_six_axis_test import (
    DEFAULT_KD,
    DEFAULT_KP,
    STARTUP_KD,
    STARTUP_KP,
    configure_motor_b_mit_mode,
    prime_feedback,
    validate_pose,
    wait_for_fresh_feedback,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDINGS_DIR = REPO_ROOT / "recordings/a1z_teach"
PARK_POSE = np.radians([0.0, 60.0, -60.0, 0.0, 0.0, 0.0])
PARK_SPEED_RAD_S = 0.20
PLAY_START_SPEED_RAD_S = 0.20
MAX_PLAY_SPEED_FACTOR = 1.0
MAX_EFFECTIVE_ARM_VELOCITY_RAD_S = 2.0
MAX_EFFECTIVE_GRIPPER_RATE_S = 4.0
SMOOTH_TARGET_PEAK_VELOCITY_RAD_S = 1.5
SMOOTH_SAMPLE_HZ = 50.0
MAX_START_JUMP_RAD = np.radians(120.0)
MAX_GRIPPER_TORQUE_NM = 0.50
MIN_FRAMES = 2
SDK_LIMIT_TOLERANCE_RAD = 0.05
INITIAL_GRAVITY_FACTOR_MAX = 0.30
MAX_GRAVITY_FACTOR = 1.0
MAX_TEMP_C = 60.0
SUPPORT_ACK = "PARKED_SUPPORTED"
OFFICIAL_SOFT_LIMITS = np.array(
    [
        [-2.094, 2.094],
        [0.0, 3.142],
        [-3.142, 0.0],
        [-1.484, 1.484],
        [-1.484, 1.484],
        [-2.007, 2.007],
    ],
    dtype=np.float64,
)


@dataclass(frozen=True)
class TrajectoryInfo:
    """Validated recording metadata."""

    frames: int
    duration_s: float
    has_gripper: bool
    max_arm_velocity_rad_s: float


def validate_gravity_factor(
    factor: float,
    *,
    high_factor_direction_confirmed: bool,
) -> None:
    """Require a low-factor direction test before higher compensation."""
    if not 0 <= factor <= MAX_GRAVITY_FACTOR:
        raise ValueError(
            f"gravity factor must be in [0, {MAX_GRAVITY_FACTOR:.1f}]"
        )
    if (
        factor > INITIAL_GRAVITY_FACTOR_MAX
        and not high_factor_direction_confirmed
    ):
        raise ValueError(
            "gravity factor above 0.30 requires confirmed compensation direction"
        )


def check_live_state(robot: Any) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Require a running loop with finite, in-limit, non-hot feedback."""
    if not robot.is_running:
        raise RuntimeError("control loop stopped")
    pose = np.asarray(robot.get_joint_pos()[:6], dtype=np.float64)
    validate_pose(pose)
    state = robot.get_joint_state()
    temperatures = np.asarray(state["temp_mos"], dtype=np.float64)
    if np.any(~np.isfinite(temperatures)):
        raise RuntimeError("non-finite motor temperature")
    if np.any(temperatures > MAX_TEMP_C):
        raise RuntimeError(
            f"MOS temperature exceeded {MAX_TEMP_C:.0f} C: "
            f"{temperatures.round(1).tolist()}"
        )
    errors = np.asarray(state["error_codes"], dtype=np.int64)
    bad = (errors != 0x0) & (errors != 0x1)
    if np.any(bad):
        raise RuntimeError(
            f"motor fault codes present: {errors.astype(int).tolist()}"
        )
    return pose, state


def wait_for_operator_support() -> None:
    """Keep requesting the exact acknowledgement before removing torque."""
    prompt = (
        "\nThe arm is still actively held. Physically support the no-brake "
        f"arm, then type {SUPPORT_ACK} to permit motor disable: "
    )
    while True:
        try:
            response = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            logging.error(
                "Support acknowledgement missing; motor disable remains blocked"
            )
            continue
        if response == SUPPORT_ACK:
            return
        logging.warning("Exact acknowledgement %s is required", SUPPORT_ACK)


def validated_recording_path(
    name: str,
    recordings_dir: Path = DEFAULT_RECORDINGS_DIR,
) -> Path:
    """Resolve a JSON recording path while keeping it in the local data dir."""
    root = recordings_dir.resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise ValueError(f"recording must be directly inside {root}")
    if candidate.suffix.lower() != ".json":
        raise ValueError("recording filename must end in .json")
    return candidate


def validate_playback_pose(position: np.ndarray) -> None:
    """Apply the gripper-branch factory limits and its 0.05-rad tolerance."""
    if position.shape != (6,) or not np.all(np.isfinite(position)):
        raise ValueError("pose must contain six finite joint values")
    below = position < OFFICIAL_SOFT_LIMITS[:, 0] - SDK_LIMIT_TOLERANCE_RAD
    above = position > OFFICIAL_SOFT_LIMITS[:, 1] + SDK_LIMIT_TOLERANCE_RAD
    if np.any(below | above):
        offenders = (np.flatnonzero(below | above) + 1).tolist()
        raise ValueError(f"pose outside official soft limits at joints {offenders}")


def validate_trajectory(
    trajectory: list[tuple[float, np.ndarray]],
    *,
    speed_factor: float,
) -> TrajectoryInfo:
    """Reject malformed, out-of-limit, or excessively fast playback data."""
    if not 0 < speed_factor <= MAX_PLAY_SPEED_FACTOR:
        raise ValueError(
            f"speed factor must be in (0, {MAX_PLAY_SPEED_FACTOR:.1f}]"
        )
    if len(trajectory) < MIN_FRAMES:
        raise ValueError(f"trajectory requires at least {MIN_FRAMES} frames")

    timestamps = np.asarray([frame[0] for frame in trajectory], dtype=np.float64)
    if (
        not np.all(np.isfinite(timestamps))
        or abs(float(timestamps[0])) > 1e-6
        or np.any(np.diff(timestamps) <= 0)
    ):
        raise ValueError(
            "trajectory timestamps must start at zero and strictly increase"
        )

    sizes = {np.asarray(frame[1]).shape for frame in trajectory}
    if len(sizes) != 1 or sizes.pop() not in {(6,), (7,)}:
        raise ValueError("every trajectory frame must contain 6 or 7 values")
    has_gripper = len(trajectory[0][1]) == 7

    positions = np.asarray([frame[1] for frame in trajectory], dtype=np.float64)
    if not np.all(np.isfinite(positions)):
        raise ValueError("trajectory contains non-finite positions")
    for index, position in enumerate(positions[:, :6]):
        try:
            validate_playback_pose(position)
        except ValueError as exc:
            raise ValueError(f"trajectory frame {index} is unsafe: {exc}") from exc
    if has_gripper and np.any(
        (positions[:, 6] < 0.0) | (positions[:, 6] > 1.0)
    ):
        raise ValueError("trajectory gripper positions must be in [0, 1]")

    dt = np.diff(timestamps)
    arm_velocity = np.abs(np.diff(positions[:, :6], axis=0)) / dt[:, None]
    max_arm_velocity = float(np.max(arm_velocity) * speed_factor)
    if max_arm_velocity > MAX_EFFECTIVE_ARM_VELOCITY_RAD_S:
        raise ValueError(
            "trajectory playback velocity "
            f"{max_arm_velocity:.2f} rad/s exceeds "
            f"{MAX_EFFECTIVE_ARM_VELOCITY_RAD_S:.2f} rad/s"
        )
    if has_gripper:
        gripper_rate = np.abs(np.diff(positions[:, 6])) / dt
        max_gripper_rate = float(np.max(gripper_rate) * speed_factor)
        if max_gripper_rate > MAX_EFFECTIVE_GRIPPER_RATE_S:
            raise ValueError(
                "trajectory gripper rate "
                f"{max_gripper_rate:.2f}/s exceeds "
                f"{MAX_EFFECTIVE_GRIPPER_RATE_S:.2f}/s"
            )

    return TrajectoryInfo(
        frames=len(trajectory),
        duration_s=float(timestamps[-1]),
        has_gripper=has_gripper,
        max_arm_velocity_rad_s=max_arm_velocity,
    )


def persist_recording(
    trajectory: list[tuple[float, np.ndarray]],
    path: Path,
    *,
    speed_factor: float,
) -> TrajectoryInfo:
    """Always preserve raw feedback, then save the normal file only if safe."""
    raw_path = path.with_name(f"{path.stem}.raw{path.suffix}")
    save_recording(trajectory, raw_path)
    logging.info("Raw recording preserved at %s", raw_path)
    info = validate_trajectory(trajectory, speed_factor=speed_factor)
    save_recording(trajectory, path)
    return info


def smooth_trajectory(
    trajectory: list[tuple[float, np.ndarray]],
) -> tuple[list[tuple[float, np.ndarray]], int]:
    """Retime implausible position steps with coordinated minimum jerk.

    Slow recorded segments retain their original timing. A segment whose
    finite-difference speed exceeds the replay gates is expanded into a
    synchronized quintic interpolation. Every original pose remains on the
    path; no joint angle is clipped or discarded.
    """
    if len(trajectory) < MIN_FRAMES:
        raise ValueError(f"trajectory requires at least {MIN_FRAMES} frames")
    smoothed = [(0.0, np.asarray(trajectory[0][1], dtype=np.float64).copy())]
    output_time = 0.0
    changed = 0

    for index in range(1, len(trajectory)):
        previous_time, previous_position = trajectory[index - 1]
        current_time, current_position = trajectory[index]
        previous = np.asarray(previous_position, dtype=np.float64)
        current = np.asarray(current_position, dtype=np.float64)
        if previous.shape != current.shape or current.shape not in {(6,), (7,)}:
            raise ValueError("every trajectory frame must contain 6 or 7 values")
        dt = float(current_time - previous_time)
        if not np.isfinite(dt) or dt <= 0:
            raise ValueError("trajectory timestamps must strictly increase")
        delta = current - previous
        arm_rate = float(np.max(np.abs(delta[:6])) / dt)
        gripper_rate = (
            float(abs(delta[6]) / dt) if current.shape == (7,) else 0.0
        )
        needs_smoothing = (
            arm_rate > MAX_EFFECTIVE_ARM_VELOCITY_RAD_S
            or gripper_rate > MAX_EFFECTIVE_GRIPPER_RATE_S
        )
        if not needs_smoothing:
            output_time += dt
            smoothed.append((output_time, current.copy()))
            continue

        changed += 1
        # Quintic minimum jerk has peak velocity 1.875 × average velocity.
        arm_duration = (
            1.875
            * float(np.max(np.abs(delta[:6])))
            / SMOOTH_TARGET_PEAK_VELOCITY_RAD_S
        )
        gripper_duration = (
            1.875 * abs(float(delta[6])) / MAX_EFFECTIVE_GRIPPER_RATE_S
            if current.shape == (7,)
            else 0.0
        )
        duration = max(dt, arm_duration, gripper_duration)
        steps = max(2, int(np.ceil(duration * SMOOTH_SAMPLE_HZ)))
        frame_period = duration / steps
        for step in range(1, steps + 1):
            fraction = step / steps
            alpha = (
                10 * fraction**3
                - 15 * fraction**4
                + 6 * fraction**5
            )
            output_time += frame_period
            smoothed.append((output_time, previous + alpha * delta))

    return smoothed, changed


def default_smoothed_path(path: Path) -> Path:
    """Choose a sibling filename that cannot overwrite the raw input."""
    stem = path.stem.removesuffix(".raw")
    return path.with_name(f"{stem}.smoothed.json")


def create_teach_robot(bus: Any, gravity_factor: float) -> Any:
    """Create the vendor ArmRobot on the already-open macOS HHS CAN bus."""
    import can
    from a1z.robots.get_robot import get_a1z_robot

    kp = DEFAULT_KP.copy()
    kp[1:3] = 60.0
    real_bus_factory = can.interface.Bus
    can.interface.Bus = lambda *args, **kwargs: bus
    try:
        robot = get_a1z_robot(
            gravity_comp_factor=gravity_factor,
            zero_gravity_mode=True,
            control_freq_hz=100,
            min_freq_hz=45.0,
            default_kp=kp,
            default_kd=DEFAULT_KD,
            with_gripper=True,
            gripper_max_torque=MAX_GRIPPER_TORQUE_NM,
        )
        robot._joint_limits = [
            tuple(limits) for limits in OFFICIAL_SOFT_LIMITS
        ]
        return robot
    finally:
        can.interface.Bus = real_bus_factory


def start_in_teach_mode(
    robot: Any,
    bus: Any,
    abort: threading.Event,
) -> None:
    """Prime feedback, then enable gravity-only hand-guiding without a snap."""
    configure_motor_b_mit_mode(robot)
    primed_pose, primed_feedback = prime_feedback(robot, bus, abort)
    logging.info("Primed pose: %s deg", np.degrees(primed_pose).round(2).tolist())
    robot.start(initial_kp=STARTUP_KP, initial_kd=STARTUP_KD)
    wait_for_fresh_feedback(robot, primed_feedback, abort)
    time.sleep(0.8)
    running_pose, state = check_live_state(robot)
    if np.max(np.abs(running_pose - primed_pose)) > 0.15:
        raise RuntimeError("zero-gain startup pose diverged from primed pose")
    logging.info(
        "Teach mode ready pose=%s deg temp=%s C status=%s",
        np.degrees(running_pose).round(2).tolist(),
        state["temp_mos"].round(1).tolist(),
        state["error_codes"].astype(int).tolist(),
    )
    robot.set_gripper_free_drive(True)


def hold_current_pose(robot: Any) -> np.ndarray:
    """Leave hand-guiding by holding the freshly measured pose."""
    current = np.asarray(robot.get_joint_pos(), dtype=np.float64)
    validate_pose(current[:6])
    robot.set_gripper_free_drive(False)
    robot.command_joint_pos(current)
    robot.set_gravity_mode(False)
    time.sleep(0.3)
    return current


def record_interactively(
    robot: Any,
    *,
    sample_hz: int,
) -> list[tuple[float, np.ndarray]]:
    """Wait for the operator and record the hand-guided arm and gripper."""
    input(
        "\nTEACH ready: support the arm, then press ENTER to start recording. "
    )
    robot.start_recording(sample_hz=sample_hz)
    print(
        "Recording: move all six joints and the gripper by hand. "
        "Press ENTER to stop."
    )
    input()
    trajectory = robot.stop_recording()
    hold_current_pose(robot)
    return trajectory


def move_to_recording_start(
    robot: Any,
    trajectory: list[tuple[float, np.ndarray]],
) -> None:
    """Use one slow minimum-jerk six-axis move to reach the first frame."""
    start = np.asarray(trajectory[0][1], dtype=np.float64)
    robot.move_joints(
        start,
        speed=PLAY_START_SPEED_RAD_S,
        max_jump_rad=MAX_START_JUMP_RAD,
    )
    time.sleep(0.3)


def play_interactively(
    robot: Any,
    trajectory: list[tuple[float, np.ndarray]],
    *,
    speed_factor: float,
) -> None:
    """Move slowly to frame zero, then use the official trajectory player."""
    info = validate_trajectory(trajectory, speed_factor=speed_factor)
    input(
        f"\nPLAY ready: {info.frames} frames, "
        f"{info.duration_s / speed_factor:.2f}s at {speed_factor:.2f}x. "
        "Clear the workspace and press ENTER to move to the start pose. "
    )
    move_to_recording_start(robot, trajectory)
    input("At start pose. Press ENTER to replay the taught motion. ")
    robot.play_trajectory(trajectory, speed_factor=speed_factor)
    logging.info("Playback complete")


def park_before_supported_disable(robot: Any) -> None:
    """Slowly park, require physical support, and only then remove torque."""
    while robot.is_running:
        try:
            if getattr(robot, "gripper", None) is not None:
                robot.command_gripper(1.0)
            robot.move_joints(
                PARK_POSE,
                speed=PARK_SPEED_RAD_S,
                max_jump_rad=MAX_START_JUMP_RAD,
            )
            logging.info("Compact parking pose commanded and held")
            break
        except KeyboardInterrupt:
            logging.warning(
                "Interrupt received during parking; retrying while torque remains on"
            )
        except Exception:
            logging.exception(
                "Automatic parking failed; keep physically supporting the arm"
            )
            break
    wait_for_operator_support()
    robot.stop()


def cleanup_robot(robot: Any, *, enable_attempted: bool) -> None:
    """Safely handle normal, partial-start, and pre-enable cleanup paths."""
    if robot.is_running:
        park_before_supported_disable(robot)
        return
    if enable_attempted:
        logging.warning(
            "Startup did not complete; physically support the arm before "
            "disabling any motors that may already be enabled"
        )
        wait_for_operator_support()
    robot._motor_chain.disable_all()
    if robot.gripper is not None:
        robot.gripper.disable()


def load_recording(path: Path) -> list[tuple[float, np.ndarray]]:
    """Load through the official SDK serializer."""
    from a1z.robots.arm_robot import ArmRobot

    return ArmRobot.load_recording(str(path))


def save_recording(
    trajectory: list[tuple[float, np.ndarray]],
    path: Path,
) -> None:
    """Save through the official SDK serializer."""
    from a1z.robots.arm_robot import ArmRobot

    path.parent.mkdir(parents=True, exist_ok=True)
    ArmRobot.save_recording(trajectory, str(path))


def run(
    command: str,
    path: Path,
    *,
    sample_hz: int,
    speed_factor: float,
    gravity_factor: float,
) -> None:
    """Run record, play, or the recommended uninterrupted session."""
    bus = open_hhs_bus()
    robot: Any | None = None
    enable_attempted = False
    try:
        robot = create_teach_robot(bus, gravity_factor)
        abort = threading.Event()

        def handle_signal(signum: int, _frame: Any) -> None:
            logging.warning(
                "Signal %s: entering guarded parking sequence", signum
            )
            abort.set()
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        # prime_feedback() enables the six arm motors before robot.start().
        # From this point onward every failure path needs operator support
        # before any fallback disable.
        enable_attempted = True
        start_in_teach_mode(robot, bus, abort)
        if command in {"record", "session"}:
            trajectory = record_interactively(robot, sample_hz=sample_hz)
            info = persist_recording(
                trajectory,
                path,
                speed_factor=speed_factor,
            )
            logging.info(
                "Saved %d frames (%.2fs, gripper=%s) to %s",
                info.frames,
                info.duration_s,
                info.has_gripper,
                path,
            )
        else:
            hold_current_pose(robot)
            trajectory = load_recording(path)
            validate_trajectory(trajectory, speed_factor=speed_factor)

        if command in {"play", "session"}:
            play_interactively(
                robot,
                trajectory,
                speed_factor=speed_factor,
            )
    finally:
        if robot is not None:
            cleanup_robot(robot, enable_attempted=enable_attempted)
        bus.shutdown()
        logging.info("CAN closed; all motors disabled after support acknowledgement")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("record", "play", "session", "smooth"),
    )
    parser.add_argument("file", help="local JSON filename, e.g. my_teach.json")
    parser.add_argument(
        "--output",
        help="smooth command output filename (default: *.smoothed.json)",
    )
    parser.add_argument("--sample-hz", type=int, default=50)
    parser.add_argument("--speed", type=float, default=0.50)
    parser.add_argument("--gravity-factor", type=float, default=0.70)
    parser.add_argument("--confirm-gravity-direction", action="store_true")
    parser.add_argument("--confirm-clear", action="store_true")
    args = parser.parse_args()

    try:
        path = validated_recording_path(args.file)
    except ValueError as exc:
        parser.error(str(exc))
    if args.command == "smooth":
        if not path.is_file():
            parser.error(f"recording does not exist: {path}")
        try:
            output_path = (
                validated_recording_path(args.output)
                if args.output
                else default_smoothed_path(path)
            )
        except ValueError as exc:
            parser.error(str(exc))
        if output_path == path:
            parser.error("smooth output must differ from input")
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        trajectory = load_recording(path)
        smoothed, changed = smooth_trajectory(trajectory)
        info = validate_trajectory(smoothed, speed_factor=1.0)
        save_recording(smoothed, output_path)
        print(
            f"smoothed recording saved: {output_path} "
            f"segments={changed} frames={info.frames} "
            f"duration={info.duration_s:.2f}s "
            f"peak={info.max_arm_velocity_rad_s:.2f}rad/s"
        )
        return 0
    if not 10 <= args.sample_hz <= 100:
        parser.error("--sample-hz must be in [10, 100]")
    if not 0 < args.speed <= MAX_PLAY_SPEED_FACTOR:
        parser.error(
            f"--speed must be in (0, {MAX_PLAY_SPEED_FACTOR:.1f}]"
        )
    try:
        validate_gravity_factor(
            args.gravity_factor,
            high_factor_direction_confirmed=args.confirm_gravity_direction,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if not args.confirm_clear:
        parser.error("--confirm-clear is required for active motion")
    if args.command == "play" and not path.is_file():
        parser.error(f"recording does not exist: {path}")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run(
        args.command,
        path,
        sample_hz=args.sample_hz,
        speed_factor=args.speed,
        gravity_factor=args.gravity_factor,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
