"""Safety wrapper for streaming G0.5 targets into the official A1Z server."""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, ClassVar, TextIO

import numpy as np

SAFE_DEFAULT_KP = np.array([30.0, 30.0, 30.0, 10.0, 10.0, 10.0])
SAFE_DEFAULT_KD = np.array([1.5, 1.5, 1.5, 1.0, 1.0, 1.0])
MAX_CARTESIAN_COMPONENT_M = 0.02
MAX_CARTESIAN_NORM_M = 0.03
MAX_CARTESIAN_JOINT_DELTA_DEG = 8.0
MAX_CARTESIAN_SPEED = 0.1
MAX_MOTION_MOS_TEMP_C = 70.0
MAX_MOTION_ROTOR_TEMP_C = 90.0


def acquire_instance_lock(lock_path: Path) -> TextIO:
    """Hold an exclusive process lock before touching the CAN interface."""
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_file.close()
        raise RuntimeError(
            f"A1Z safe server is already running (lock: {lock_path})"
        ) from exc
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    return lock_file


def start_robot_with_complete_feedback(robot: Any, timeout_s: float = 3.0) -> None:
    """Start an ArmRobot without treating missing USB/IP feedback as zero pose."""
    robot._motor_chain.enable_all()
    if robot.gripper is not None:
        robot.gripper.enable()
        robot.gripper.home()
        robot._motor_chain.register_external_motor(robot.gripper._motor)

    zeros = np.zeros(robot._num_joints)
    probe_kd = np.full(robot._num_joints, 0.05)
    deadline = time.monotonic() + timeout_s
    feedback_complete = False
    while time.monotonic() < deadline:
        robot._motor_chain.send_commands(zeros, zeros, zeros, probe_kd, zeros)
        time.sleep(0.02)
        robot._motor_chain.drain_and_update(robot._bus, timeout=0.005, max_messages=64)
        motors = robot._motor_chain._motor_a_list + robot._motor_chain._motor_b_list
        if all(motor.last_feedback is not None for motor in motors):
            feedback_complete = True
            break

    if not feedback_complete:
        robot._motor_chain.disable_all()
        if robot.gripper is not None:
            robot.gripper.disable()
        raise RuntimeError("startup refused: complete feedback from all six joints was not received")

    robot._read_state()
    robot.resolve_startup_joint_turns()
    if robot._joint_limits is not None:
        robot._check_joint_limits(robot._state.pos)
    with robot._command_lock:
        robot._command.pos = robot._state.pos.copy()
        robot._command.vel = zeros.copy()
        robot._command.acc = zeros.copy()
        robot._command.kp = robot._default_kp.copy()
        robot._command.kd = robot._default_kd.copy()
        robot._command.torque_ff = zeros.copy()

    robot._stop_event.clear()
    robot._running = True
    robot._estop_latch.clear()
    robot._last_feedback_t = time.time()
    robot._thread = threading.Thread(
        target=robot._control_loop, name="arm_control_loop", daemon=True
    )
    robot._thread.start()
    print(
        "[a1z-safe] complete startup feedback acquired; holding "
        f"{np.round(np.rad2deg(robot._state.pos), 2).tolist()} deg",
        flush=True,
    )


def validate_stream_target(
    joints_deg: object,
    current_deg: np.ndarray,
    limits_rad: list[tuple[float, float]],
    max_jump_deg: float,
    locked_joint_indices: tuple[int, ...] = (),
) -> np.ndarray:
    target_deg = np.asarray(joints_deg, dtype=np.float64)
    current_deg = np.asarray(current_deg, dtype=np.float64)
    if target_deg.shape != (6,) or current_deg.shape != (6,):
        raise ValueError("stream target and current state must contain six joints")
    if not np.all(np.isfinite(target_deg)):
        raise ValueError("stream target contains NaN or infinity")
    if not math.isfinite(max_jump_deg) or not 0 < max_jump_deg <= 5.0:
        raise ValueError("max_jump_deg must be in (0, 5]")
    limits = np.rad2deg(np.asarray(limits_rad, dtype=np.float64))
    locked = np.zeros(6, dtype=bool)
    locked[list(locked_joint_indices)] = True
    locked_error = np.abs(target_deg - current_deg)
    if np.any(locked & (locked_error > 0.1)):
        idx = int(np.flatnonzero(locked & (locked_error > 0.1))[0])
        raise ValueError(f"locked J{idx + 1} target must equal measured position")
    below = target_deg < limits[:, 0]
    above = target_deg > limits[:, 1]
    recovering_low = below & (current_deg < limits[:, 0]) & (target_deg > current_deg)
    recovering_high = above & (current_deg > limits[:, 1]) & (target_deg < current_deg)
    bad = np.flatnonzero(
        ~locked & (below | above) & ~(recovering_low | recovering_high)
    )
    if bad.size:
        raise ValueError(f"stream target violates joint limits at J{int(bad[0]) + 1}")
    jump = np.where(locked, 0.0, np.abs(target_deg - current_deg))
    if np.any(jump > max_jump_deg):
        idx = int(np.argmax(jump))
        raise ValueError(
            f"stream target jump J{idx + 1}={jump[idx]:.2f}deg exceeds {max_jump_deg:.2f}deg"
        )
    return np.deg2rad(target_deg)


def validate_blocking_move_target(
    joints_deg: object,
    current_deg: object,
    limits_rad: object,
    *,
    locked_joint_indices: tuple[int, ...] = (),
) -> np.ndarray:
    """Validate a recovery move while replacing client-owned locked axes."""
    requested = np.asarray(joints_deg, dtype=np.float64)
    current = np.asarray(current_deg, dtype=np.float64)
    limits = np.rad2deg(np.asarray(limits_rad, dtype=np.float64))
    if requested.shape != (6,) or current.shape != (6,) or limits.shape != (6, 2):
        raise ValueError("blocking move target, state, and limits must describe six joints")
    if not np.all(np.isfinite(requested)) or not np.all(np.isfinite(current)):
        raise ValueError("blocking move target or state contains NaN or infinity")
    target = requested.copy()
    target[list(locked_joint_indices)] = current[list(locked_joint_indices)]
    locked = np.zeros(6, dtype=bool)
    locked[list(locked_joint_indices)] = True
    below = target < limits[:, 0]
    above = target > limits[:, 1]
    recovering_low = below & (current < limits[:, 0]) & (target > current)
    recovering_high = above & (current > limits[:, 1]) & (target < current)
    bad = np.flatnonzero(
        ~locked & (below | above) & ~(recovering_low | recovering_high)
    )
    if bad.size:
        raise ValueError(
            f"blocking move violates soft limits at J{int(bad[0]) + 1}"
        )
    return np.deg2rad(target)


def validate_blocking_move_execution(
    target_rad: object,
    measured_rad: object,
    *,
    tolerance_deg: float = 1.5,
) -> np.ndarray:
    """Require a blocking joint move to finish at its measured target."""
    target = np.asarray(target_rad, dtype=np.float64)
    measured = np.asarray(measured_rad, dtype=np.float64)
    if target.shape != (6,) or measured.shape != (6,):
        raise ValueError("blocking move target and measurement must contain six joints")
    if not np.all(np.isfinite(target)) or not np.all(np.isfinite(measured)):
        raise ValueError("blocking move target or measurement contains NaN or infinity")
    if not math.isfinite(tolerance_deg) or not 0 < tolerance_deg <= 2:
        raise ValueError("blocking move tolerance_deg must be in (0, 2]")

    error_deg = np.abs(np.rad2deg(target - measured))
    outside = np.flatnonzero(error_deg > tolerance_deg)
    if outside.size:
        index = int(outside[np.argmax(error_deg[outside])])
        raise RuntimeError(
            f"blocking move did not arrive: J{index + 1} "
            f"error={error_deg[index]:.2f}deg exceeds {tolerance_deg:.2f}deg"
        )
    return error_deg


def validate_motion_health(
    error_codes: object,
    temp_mos_c: object,
    temp_rotor_c: object,
    *,
    max_mos_c: float = MAX_MOTION_MOS_TEMP_C,
    max_rotor_c: float = MAX_MOTION_ROTOR_TEMP_C,
) -> None:
    """Reject every new motion command when motor health is unsafe."""
    codes = np.asarray(error_codes)
    mos = np.asarray(temp_mos_c, dtype=np.float64)
    rotor = np.asarray(temp_rotor_c, dtype=np.float64)
    if codes.shape != (6,) or mos.shape != (6,) or rotor.shape != (6,):
        raise RuntimeError("motion refused because six-joint motor health is incomplete")
    if (
        not np.all(np.isfinite(codes))
        or not np.all(np.isfinite(mos))
        or not np.all(np.isfinite(rotor))
    ):
        raise RuntimeError("motion refused because motor health contains NaN or infinity")
    normalized_codes = [int(value) for value in codes.tolist()]
    if any(code not in (0x0, 0x1) for code in normalized_codes):
        raise RuntimeError(
            f"motion refused due to motor error codes: {normalized_codes}"
        )
    if not math.isfinite(max_mos_c) or not math.isfinite(max_rotor_c):
        raise ValueError("motion temperature thresholds must be finite")
    hottest_mos = float(np.max(mos))
    hottest_rotor = float(np.max(rotor))
    if hottest_mos >= max_mos_c:
        raise RuntimeError(
            f"motion refused: MOS temperature {hottest_mos:.1f}C "
            f"reached {max_mos_c:.1f}C limit"
        )
    if hottest_rotor >= max_rotor_c:
        raise RuntimeError(
            f"motion refused: rotor temperature {hottest_rotor:.1f}C "
            f"reached {max_rotor_c:.1f}C limit"
        )


def build_tool_pose_data(kinematics: object, joints_rad: object) -> dict[str, object]:
    """Return the measured base-to-arm_link6 pose used by wrist calibration."""
    joints = np.asarray(joints_rad, dtype=np.float64)
    if joints.shape != (6,) or not np.all(np.isfinite(joints)):
        raise ValueError("tool pose requires six finite measured joints")
    fk = getattr(kinematics, "fk", None)
    if not callable(fk):
        raise TypeError("kinematics must provide fk(joints)")
    pose = np.asarray(fk(joints), dtype=np.float64)
    if pose.shape != (4, 4) or not np.all(np.isfinite(pose)):
        raise RuntimeError("tool FK returned an invalid 4x4 pose")
    if not np.allclose(pose[3], [0.0, 0.0, 0.0, 1.0], atol=1e-6):
        raise RuntimeError("tool FK returned a non-homogeneous pose")
    return {
        "base_from_tool": np.round(pose, 9).tolist(),
        "tcp_m": np.round(pose[:3, 3], 9).tolist(),
    }


def preserve_locked_joint_targets(
    requested_deg: object,
    server_command_deg: np.ndarray,
    locked_joint_indices: tuple[int, ...] = (),
) -> np.ndarray:
    """Replace client values for locked axes with the server-owned targets."""
    requested = np.asarray(requested_deg, dtype=np.float64)
    server_command = np.asarray(server_command_deg, dtype=np.float64)
    if requested.shape != (6,) or server_command.shape != (6,):
        raise ValueError("requested and server command must contain six joints")
    result = requested.copy()
    result[list(locked_joint_indices)] = server_command[list(locked_joint_indices)]
    return result


def build_watchdog_hold_target(
    measured_rad: object,
    server_command_rad: object,
    locked_joint_indices: tuple[int, ...] = (),
) -> np.ndarray:
    """Hold measured movable axes without ratcheting locked-axis drift."""
    measured = np.asarray(measured_rad, dtype=np.float64)
    server_command = np.asarray(server_command_rad, dtype=np.float64)
    if measured.shape != (6,) or server_command.shape != (6,):
        raise ValueError("measured and server command must contain six joints")
    if not np.all(np.isfinite(measured)) or not np.all(np.isfinite(server_command)):
        raise ValueError("measured and server command joints must be finite")
    result = measured.copy()
    result[list(locked_joint_indices)] = server_command[list(locked_joint_indices)]
    return result


def validate_cartesian_delta(
    delta_m: object,
    *,
    max_component_m: float = MAX_CARTESIAN_COMPONENT_M,
    max_norm_m: float = MAX_CARTESIAN_NORM_M,
) -> np.ndarray:
    """Validate one small base-frame TCP translation waypoint."""
    delta = np.asarray(delta_m, dtype=np.float64)
    if delta.shape != (3,):
        raise ValueError("delta_m must contain exactly [x, y, z] metres")
    if not np.all(np.isfinite(delta)):
        raise ValueError("delta_m contains NaN or infinity")
    if not math.isfinite(max_component_m) or not 0 < max_component_m <= 0.02:
        raise ValueError("max_component_m must be in (0, 0.02]")
    if not math.isfinite(max_norm_m) or not 0 < max_norm_m <= 0.03:
        raise ValueError("max_norm_m must be in (0, 0.03]")
    if np.any(np.abs(delta) > max_component_m):
        raise ValueError(
            f"Cartesian component exceeds {max_component_m * 1000:.0f} mm"
        )
    norm = float(np.linalg.norm(delta))
    if norm == 0:
        raise ValueError("Cartesian delta must be non-zero")
    if norm > max_norm_m:
        raise ValueError(f"Cartesian delta exceeds {max_norm_m * 1000:.0f} mm")
    return delta


def validate_cartesian_solution(
    target_rad: object,
    current_rad: object,
    limits_rad: object,
    *,
    max_joint_delta_deg: float = MAX_CARTESIAN_JOINT_DELTA_DEG,
    locked_joint_indices: tuple[int, ...] = (),
) -> np.ndarray:
    """Reject IK results that leave limits, jump, or move a locked joint."""
    target = np.asarray(target_rad, dtype=np.float64)
    current = np.asarray(current_rad, dtype=np.float64)
    limits = np.asarray(limits_rad, dtype=np.float64)
    if target.shape != (6,) or current.shape != (6,) or limits.shape != (6, 2):
        raise ValueError("Cartesian IK state and limits must describe six joints")
    if not np.all(np.isfinite(target)) or not np.all(np.isfinite(current)):
        raise ValueError("Cartesian IK state contains NaN or infinity")
    if not math.isfinite(max_joint_delta_deg) or not 0 < max_joint_delta_deg <= 8:
        raise ValueError("max_joint_delta_deg must be in (0, 8]")

    locked = np.zeros(6, dtype=bool)
    locked[list(locked_joint_indices)] = True
    delta_deg = np.abs(np.rad2deg(target - current))
    moved_locked = np.flatnonzero(locked & (delta_deg > 0.1))
    if moved_locked.size:
        raise ValueError(f"Cartesian IK moved locked J{int(moved_locked[0]) + 1}")

    below = target < limits[:, 0]
    above = target > limits[:, 1]
    recovering_low = below & (current < limits[:, 0]) & (target > current)
    recovering_high = above & (current > limits[:, 1]) & (target < current)
    bad_limit = np.flatnonzero(
        ~locked & (below | above) & ~(recovering_low | recovering_high)
    )
    if bad_limit.size:
        raise ValueError(
            f"Cartesian IK violates soft limits at J{int(bad_limit[0]) + 1}"
        )

    bad_jump = np.flatnonzero(~locked & (delta_deg > max_joint_delta_deg))
    if bad_jump.size:
        index = int(bad_jump[np.argmax(delta_deg[bad_jump])])
        raise ValueError(
            f"Cartesian IK jump J{index + 1}={delta_deg[index]:.2f}deg "
            f"exceeds {max_joint_delta_deg:.2f}deg"
        )
    return target


def validate_cartesian_execution(
    requested_delta_m: object,
    before_tcp_m: object,
    after_tcp_m: object,
    before_joints_rad: object,
    after_joints_rad: object,
    *,
    locked_joint_indices: tuple[int, ...] = (),
    max_locked_drift_deg: float = 1.0,
) -> np.ndarray:
    """Require measured TCP progress to match the requested direction and distance."""
    requested = np.asarray(requested_delta_m, dtype=np.float64)
    before_tcp = np.asarray(before_tcp_m, dtype=np.float64)
    after_tcp = np.asarray(after_tcp_m, dtype=np.float64)
    before_joints = np.asarray(before_joints_rad, dtype=np.float64)
    after_joints = np.asarray(after_joints_rad, dtype=np.float64)
    if (
        requested.shape != (3,)
        or before_tcp.shape != (3,)
        or after_tcp.shape != (3,)
        or before_joints.shape != (6,)
        or after_joints.shape != (6,)
    ):
        raise ValueError("Cartesian execution evidence has invalid dimensions")
    if not all(
        np.all(np.isfinite(values))
        for values in (
            requested,
            before_tcp,
            after_tcp,
            before_joints,
            after_joints,
        )
    ):
        raise ValueError("Cartesian execution evidence contains NaN or infinity")
    if (
        not math.isfinite(max_locked_drift_deg)
        or not 0 < max_locked_drift_deg <= 1
    ):
        raise ValueError("max_locked_drift_deg must be in (0, 1]")

    achieved = after_tcp - before_tcp
    requested_norm = float(np.linalg.norm(requested))
    error = float(np.linalg.norm(achieved - requested))
    tolerance = max(0.003, requested_norm * 0.35)
    progress = float(np.dot(achieved, requested))
    if progress <= 0:
        raise RuntimeError("measured TCP moved opposite the requested direction")
    if error > tolerance:
        raise RuntimeError(
            f"measured TCP error {error * 1000:.1f} mm exceeds "
            f"{tolerance * 1000:.1f} mm"
        )

    locked = np.asarray(locked_joint_indices, dtype=np.int64)
    if locked.size:
        drift = np.abs(np.rad2deg(after_joints[locked] - before_joints[locked]))
        if np.any(drift > max_locked_drift_deg):
            index = int(locked[int(np.argmax(drift))])
            raise RuntimeError(
                f"locked J{index + 1} drifted {float(np.max(drift)):.2f}deg"
            )
    return achieved


def main() -> None:
    parser = argparse.ArgumentParser(description="50 Hz watchdog-protected A1Z server")
    parser.add_argument("--a1z-dir", default="~/GALAXEA-A1Z")
    parser.add_argument("--can", default="can0")
    parser.add_argument("--control-hz", type=int, default=50)
    parser.add_argument("--min-hz", type=float, default=40.0)
    parser.add_argument("--watchdog-s", type=float, default=0.35)
    parser.add_argument("--max-stream-jump-deg", type=float, default=3.0)
    parser.add_argument("--lock-path", default="/tmp/a1z-safe-server.lock")
    parser.add_argument(
        "--unlock-j4",
        action="store_true",
        help="Allow J4 motion for supervised Cartesian depth testing",
    )
    parser.add_argument(
        "--j4-kp",
        type=float,
        default=float(SAFE_DEFAULT_KP[3]),
        help="J4 position gain; must remain in (0, 30]",
    )
    args = parser.parse_args()
    if not math.isfinite(args.j4_kp) or not 0 < args.j4_kp <= 30:
        parser.error("--j4-kp must be in (0, 30]")

    # Acquire this before constructing the robot: construction opens CAN and a
    # second control loop would contend with the first even if socket bind fails.
    _instance_lock = acquire_instance_lock(Path(args.lock_path).expanduser())

    a1z_dir = Path(args.a1z_dir).expanduser()
    sys.path.insert(0, str(a1z_dir))
    from a1z.robots.get_robot import get_a1z_robot
    from a1z.robots.server import PRESETS, RobotServer

    from a1z_g05.mapping import A1Z_SOFT_LIMITS_RAD
    from a1z_g05.retargeting import PinocchioKinematics

    # USB/IP adds enough latency that the stock 250 Hz gains become unstable
    # at 50 Hz. Start deliberately soft and damped; tune upward only from
    # measured step responses.
    locked_joint_indices = () if args.unlock_j4 else (3,)
    default_kp = SAFE_DEFAULT_KP.copy()
    default_kd = SAFE_DEFAULT_KD.copy()
    default_kp[3] = args.j4_kp
    robot = get_a1z_robot(
        can_channel=args.can,
        zero_gravity_mode=False,
        with_gripper=True,
        gravity_comp_factor=1.0,
        control_freq_hz=args.control_hz,
        min_freq_hz=args.min_hz,
        default_kp=default_kp,
        default_kd=default_kd,
    )

    class SafeRobotServer(RobotServer):
        def __init__(self) -> None:
            super().__init__(robot, with_gripper=True)
            self._stream_lock = threading.Lock()
            self._stream_active = False
            self._last_stream_time = 0.0
            self._last_stream_target_deg: np.ndarray | None = None
            self._watchdog_thread: threading.Thread | None = None
            self._cartesian_kinematics: PinocchioKinematics | None = None

        def _get_cartesian_kinematics(self) -> PinocchioKinematics:
            if self._cartesian_kinematics is None:
                self._cartesian_kinematics = PinocchioKinematics(
                    str(
                        a1z_dir
                        / "a1z"
                        / "robot_models"
                        / "a1z"
                        / "A1Z_G1Z.urdf"
                    ),
                    "arm_link6",
                    locked_joint_indices=list(locked_joint_indices),
                )
            return self._cartesian_kinematics

        def _cmd_status_safe(self, request_args: dict) -> dict:
            response = super()._cmd_status(request_args)
            with robot._command_lock:
                command_deg = np.rad2deg(robot._command.pos.copy())
            measured_deg = np.asarray(response["data"]["pos_deg"], dtype=np.float64)
            with self._stream_lock:
                stream_active = self._stream_active
                age = time.monotonic() - self._last_stream_time if stream_active else None
            response["data"].update(
                {
                    "command_deg": np.round(command_deg, 3).tolist(),
                    "tracking_error_deg": np.round(command_deg - measured_deg, 3).tolist(),
                    "control_thread_alive": (
                        robot._thread is not None and robot._thread.is_alive()
                    ),
                    "estopped": robot._estop_latch.is_set(),
                    "stream_active": stream_active,
                    "stream_age_s": None if age is None else round(age, 3),
                    "control_hz": args.control_hz,
                    "watchdog_s": args.watchdog_s,
                    "locked_joint_indices": list(locked_joint_indices),
                    "default_kp": np.round(robot._default_kp, 3).tolist(),
                }
            )
            return response

        def _cmd_tool_pose(self, _request_args: dict) -> dict:
            return {
                "ok": True,
                "data": build_tool_pose_data(
                    self._get_cartesian_kinematics(),
                    robot.get_joint_pos()[:6],
                ),
            }

        def _cmd_stream(self, request_args: dict) -> dict:
            state = robot.get_joint_state()
            if robot.is_estopped:
                raise RuntimeError("action stream refused while A1Z is estopped")
            validate_motion_health(
                state["error_codes"],
                state["temp_mos"],
                state["temp_rotor"],
            )
            current_deg = np.rad2deg(state["pos"][:6])
            with robot._command_lock:
                command_deg = np.rad2deg(robot._command.pos.copy())
            requested_deg = preserve_locked_joint_targets(
                request_args.get("joints_deg"),
                command_deg,
                locked_joint_indices,
            )
            validation_current_deg = current_deg.copy()
            validation_current_deg[list(locked_joint_indices)] = command_deg[
                list(locked_joint_indices)
            ]
            target_rad = validate_stream_target(
                requested_deg,
                validation_current_deg,
                robot.get_robot_info()["joint_limits"],
                min(
                    float(request_args.get("max_jump_deg", args.max_stream_jump_deg)),
                    args.max_stream_jump_deg,
                ),
                locked_joint_indices,
            )
            gripper = float(request_args.get("gripper", robot.get_gripper_pos()))
            if not math.isfinite(gripper) or not 0.0 <= gripper <= 1.0:
                raise ValueError("gripper must be finite and in [0, 1]")
            with robot._command_lock:
                robot._command.pos = target_rad.copy()
                robot._command.kp = robot._default_kp.copy()
                robot._command.kd = robot._default_kd.copy()
                robot._command.torque_ff = np.zeros(6)
            robot.command_gripper(gripper)
            target_deg = np.rad2deg(target_rad)
            with self._stream_lock:
                self._last_stream_target_deg = target_deg
                self._last_stream_time = time.monotonic()
                self._stream_active = True
            return {
                "ok": True,
                "data": {"accepted_deg": np.round(target_deg, 3).tolist(), "gripper": gripper},
            }

        def _cmd_hold(self, _request_args: dict) -> dict:
            measured = robot.get_joint_pos()[:6]
            with robot._command_lock:
                robot._command.pos = build_watchdog_hold_target(
                    measured,
                    robot._command.pos,
                    locked_joint_indices,
                )
                robot._command.kp = robot._default_kp.copy()
                robot._command.kd = robot._default_kd.copy()
                robot._command.torque_ff = np.zeros(6)
            with self._stream_lock:
                self._stream_active = False
                self._last_stream_target_deg = None
            return {"ok": True, "data": {"holding_deg": np.round(np.rad2deg(measured), 3).tolist()}}

        def _cmd_move_safe(self, request_args: dict) -> dict:
            speed = float(request_args.get("speed", 0.1))
            if not math.isfinite(speed) or not 0 < speed <= 0.15:
                raise ValueError("blocking move speed must be in (0, 0.15]")
            with self._stream_lock:
                if self._stream_active:
                    raise RuntimeError("blocking move refused while an action stream is active")
            state = robot.get_joint_state()
            if robot.is_estopped:
                raise RuntimeError("blocking move refused while A1Z is estopped")
            validate_motion_health(
                state["error_codes"],
                state["temp_mos"],
                state["temp_rotor"],
            )
            current_deg = np.rad2deg(state["pos"][:6])
            if "preset" in request_args:
                name = str(request_args["preset"])
                if name not in PRESETS:
                    raise ValueError(f"unknown A1Z preset: {name}")
                requested_deg = np.rad2deg(PRESETS[name])
            elif "joints" in request_args:
                requested_deg = request_args["joints"]
            else:
                raise ValueError("move requires 'preset' or 'joints'")
            target = validate_blocking_move_target(
                requested_deg,
                current_deg,
                A1Z_SOFT_LIMITS_RAD,
                locked_joint_indices=locked_joint_indices,
            )
            robot.move_joints(target, speed=speed)
            # ``move_joints`` blocks for the command-space trajectory, not for
            # measured convergence. Give the low-bandwidth USB/IP loop a short
            # settling window, then reject the old false-positive "Arrived".
            time.sleep(1.0)
            measured_deg = np.rad2deg(robot.get_joint_pos()[:6])
            validate_blocking_move_execution(
                target,
                np.deg2rad(measured_deg),
            )
            return {
                "ok": True,
                "data": {
                    "pos_deg": np.round(measured_deg, 2).tolist(),
                    "target_deg": np.round(np.rad2deg(target), 3).tolist(),
                    "locked_joint_indices": list(locked_joint_indices),
                },
            }

        def _cmd_move_tool_delta(self, request_args: dict) -> dict:
            if request_args.get("frame", "base") != "base":
                raise ValueError("move_tool_delta only accepts frame='base'")
            delta = validate_cartesian_delta(request_args.get("delta_m"))
            speed = float(request_args.get("speed", 0.08))
            if not math.isfinite(speed) or not 0 < speed <= MAX_CARTESIAN_SPEED:
                raise ValueError(
                    f"Cartesian speed must be in (0, {MAX_CARTESIAN_SPEED}]"
                )
            with self._stream_lock:
                if self._stream_active:
                    raise RuntimeError(
                        "Cartesian move refused while an action stream is active"
                    )

            state = robot.get_joint_state()
            if robot.is_estopped:
                raise RuntimeError("Cartesian move refused while A1Z is estopped")
            validate_motion_health(
                state["error_codes"],
                state["temp_mos"],
                state["temp_rotor"],
            )

            current = np.asarray(state["pos"][:6], dtype=np.float64)
            kinematics = self._get_cartesian_kinematics()
            before_pose = kinematics.fk(current)
            requested_pose = before_pose.copy()
            requested_pose[:3, 3] += delta
            converged, target = kinematics.ik_position(
                requested_pose[:3, 3],
                current,
            )
            if not converged:
                raise ValueError("Cartesian IK did not converge")
            target = validate_cartesian_solution(
                target,
                current,
                A1Z_SOFT_LIMITS_RAD,
                locked_joint_indices=locked_joint_indices,
            )

            robot.move_joints(target, speed=speed)
            time.sleep(0.25)
            measured = robot.get_joint_pos()[:6]
            after_pose = kinematics.fk(measured)
            try:
                achieved_delta = validate_cartesian_execution(
                    delta,
                    before_pose[:3, 3],
                    after_pose[:3, 3],
                    current,
                    measured,
                    locked_joint_indices=locked_joint_indices,
                )
            except RuntimeError:
                with robot._command_lock:
                    robot._command.pos = measured.copy()
                    robot._command.kp = robot._default_kp.copy()
                    robot._command.kd = robot._default_kd.copy()
                    robot._command.torque_ff = np.zeros(6)
                raise
            return {
                "ok": True,
                "data": {
                    "frame": "base",
                    "requested_delta_m": np.round(delta, 6).tolist(),
                    "before_tcp_m": np.round(before_pose[:3, 3], 6).tolist(),
                    "requested_tcp_m": np.round(
                        requested_pose[:3, 3], 6
                    ).tolist(),
                    "after_tcp_m": np.round(after_pose[:3, 3], 6).tolist(),
                    "achieved_delta_m": np.round(achieved_delta, 6).tolist(),
                    "target_deg": np.round(np.rad2deg(target), 3).tolist(),
                    "measured_deg": np.round(np.rad2deg(measured), 3).tolist(),
                    "speed": speed,
                },
            }

        def _watchdog_loop(self) -> None:
            while not self._shutdown.wait(0.02):
                with self._stream_lock:
                    expired = (
                        self._stream_active
                        and time.monotonic() - self._last_stream_time > args.watchdog_s
                    )
                    if expired:
                        self._stream_active = False
                        self._last_stream_target_deg = None
                if expired:
                    measured = robot.get_joint_pos()[:6]
                    with robot._command_lock:
                        robot._command.pos = build_watchdog_hold_target(
                            measured,
                            robot._command.pos,
                            locked_joint_indices,
                        )
                        robot._command.kp = robot._default_kp.copy()
                        robot._command.kd = robot._default_kd.copy()
                        robot._command.torque_ff = np.zeros(6)
                    print("[a1z-safe] stream watchdog expired; holding measured position", flush=True)

        def run(self, socket_path: str = "/tmp/a1z.sock") -> None:
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True, name="A1ZStreamWatchdog"
            )
            self._watchdog_thread.start()
            super().run(socket_path)

        _HANDLERS: ClassVar[dict[str, Any]] = {
            **RobotServer._HANDLERS,
            "status": _cmd_status_safe,
            "move": _cmd_move_safe,
            "stream": _cmd_stream,
            "hold": _cmd_hold,
            "tool_pose": _cmd_tool_pose,
            "move_tool_delta": _cmd_move_tool_delta,
        }

    server = SafeRobotServer()

    def shutdown(_sig: int, _frame: Any) -> None:
        server._shutdown.set()

    import signal

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    start_robot_with_complete_feedback(robot)
    print(
        f"[a1z-safe] ready: {args.control_hz}Hz, min={args.min_hz}Hz, "
        f"watchdog={args.watchdog_s}s",
        flush=True,
    )
    try:
        server.run()
    finally:
        robot.stop()
        print("[a1z-safe] stopped", flush=True)


if __name__ == "__main__":
    main()
