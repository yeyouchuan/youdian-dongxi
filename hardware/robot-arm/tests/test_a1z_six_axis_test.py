import threading

import numpy as np
import pytest

import scripts.a1z_six_axis_test as six_axis
from scripts.a1z_six_axis_test import (
    SOFT_LIMITS,
    attempt_safe_baseline_return,
    configure_motor_b_mit_mode,
    make_joint_targets,
    measured_move_passed,
    validate_pose,
    wait_for_fresh_feedback,
)


def test_targets_move_toward_limit_midpoints() -> None:
    baseline = np.array([-0.1, 0.01, -0.01, 0.0, 0.0, 0.0])
    targets = make_joint_targets(baseline, np.radians(20))
    deltas = np.array([target[i] - baseline[i] for i, target in enumerate(targets)])

    assert np.allclose(np.degrees(deltas), [20, 20, -20, 20, 20, 20])
    assert all(np.all(target >= SOFT_LIMITS[:, 0]) for target in targets)
    assert all(np.all(target <= SOFT_LIMITS[:, 1]) for target in targets)


def test_validate_pose_rejects_joint_limit_violation() -> None:
    with pytest.raises(ValueError, match="joints \\[2\\]"):
        validate_pose(np.array([0.0, -0.1, -0.2, 0.0, 0.0, 0.0]))


def test_joint4_uses_strict_urdf_limit() -> None:
    assert SOFT_LIMITS[3].tolist() == [-1.309, 1.309]
    with pytest.raises(ValueError, match=r"joints \[4\]"):
        validate_pose(np.array([0.0, 0.1, -0.1, 1.35, 0.0, 0.0]))


def test_measured_move_requires_direction_and_progress() -> None:
    assert measured_move_passed(0.0, 1.0, 0.8)
    assert not measured_move_passed(0.0, 0.0, 0.0)
    assert not measured_move_passed(0.0, 1.0, 0.5)
    assert not measured_move_passed(0.0, 1.0, -0.8)
    assert not measured_move_passed(0.0, 1.0, 1.5)


def test_high_gravity_factor_requires_direction_confirmation() -> None:
    six_axis.validate_gravity_factor(
        0.30,
        high_factor_direction_confirmed=False,
    )
    six_axis.validate_gravity_factor(
        0.50,
        high_factor_direction_confirmed=True,
    )

    with pytest.raises(ValueError, match="confirmed compensation direction"):
        six_axis.validate_gravity_factor(
            0.50,
            high_factor_direction_confirmed=False,
        )
    with pytest.raises(ValueError, match=r"\[0, 1.0\]"):
        six_axis.validate_gravity_factor(
            1.01,
            high_factor_direction_confirmed=True,
        )


class FakeMotor:
    def __init__(self, motor_id: int, last_feedback: object | None) -> None:
        self.motor_id = motor_id
        self.last_feedback = last_feedback
        self.ctrl_modes: list[int] = []

    def set_ctrl_mode(self, mode: int) -> None:
        self.ctrl_modes.append(mode)


class FakeChain:
    def __init__(self, motors: list[FakeMotor]) -> None:
        self._motor_a_list = motors[:3]
        self._motor_b_list = motors[3:]


class FakeRobot:
    def __init__(self, motors: list[FakeMotor]) -> None:
        self._motor_chain = FakeChain(motors)


def test_configure_motor_b_mit_mode_only_updates_last_three_motors() -> None:
    motors = [FakeMotor(i + 1, object()) for i in range(6)]

    configure_motor_b_mit_mode(FakeRobot(motors))

    assert [motor.ctrl_modes for motor in motors] == [[], [], [], [1], [1], [1]]


def test_fresh_feedback_requires_new_object_from_every_motor() -> None:
    old = [object() for _ in range(6)]
    motors = [FakeMotor(i + 1, item) for i, item in enumerate(old)]
    robot = FakeRobot(motors)

    for motor in motors:
        motor.last_feedback = object()

    wait_for_fresh_feedback(
        robot,
        dict(enumerate(old, start=1)),
        abort=threading.Event(),
        timeout=0.01,
    )


def test_fresh_feedback_reports_missing_motor() -> None:
    old = [object() for _ in range(6)]
    motors = [FakeMotor(i + 1, object()) for i in range(6)]
    motors[-1].last_feedback = None
    robot = FakeRobot(motors)

    with pytest.raises(RuntimeError, match=r"CAN IDs \[6\]"):
        wait_for_fresh_feedback(
            robot,
            dict(enumerate(old, start=1)),
            abort=threading.Event(),
            timeout=0.001,
        )


class FakeReturningRobot:
    def __init__(self, pose: np.ndarray) -> None:
        self.pose = pose.copy()
        self.is_running = True
        self.move_count = 0

    def get_joint_pos(self) -> np.ndarray:
        return self.pose.copy()

    def move_joints(self, target: np.ndarray, **_kwargs: object) -> None:
        self.move_count += 1
        self.pose = target.copy()


def test_safe_baseline_return_moves_before_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(six_axis.time, "sleep", lambda _seconds: None)
    baseline = np.array([0.0, 0.2, -0.2, 0.0, 0.0, 0.0])
    robot = FakeReturningRobot(
        baseline + np.array([0.0, 0.0, 0.0, 0.2, 0.0, 0.0])
    )

    assert attempt_safe_baseline_return(
        robot, baseline, threading.Event(), speed=0.08
    )
    assert robot.move_count == 1
    assert np.allclose(robot.pose, baseline)


def test_safe_baseline_return_skips_after_abort() -> None:
    baseline = np.array([0.0, 0.2, -0.2, 0.0, 0.0, 0.0])
    robot = FakeReturningRobot(baseline)
    abort = threading.Event()
    abort.set()

    assert not attempt_safe_baseline_return(robot, baseline, abort, speed=0.08)
    assert robot.move_count == 0
