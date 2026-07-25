import ast
from pathlib import Path

import numpy as np

from scripts import a1z_safe_shutdown as shutdown


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeRobot:
    def __init__(self, pose: np.ndarray) -> None:
        self.pose = pose.copy()
        self.commands: list[np.ndarray] = []
        self.is_running = True
        self.stopped = False

    def get_joint_pos(self) -> np.ndarray:
        return self.pose.copy()

    def command_joint_pos(self, command: np.ndarray) -> None:
        self.pose = command.copy()
        self.commands.append(command.copy())

    def stop(self) -> None:
        self.stopped = True
        self.is_running = False


def test_minimum_jerk_generates_exactly_60_frames_to_zero() -> None:
    start = np.radians([10, 20, -30, 40, -50, 60])

    commands = shutdown.minimum_jerk_zero_frames(start)

    assert commands.shape == (60, 6)
    assert np.allclose(commands[-1], np.zeros(6))
    assert np.all(np.abs(commands[1:]) <= np.abs(commands[:-1]) + 1e-12)


def test_animate_to_zero_does_not_disable_robot() -> None:
    robot = FakeRobot(np.radians([10, 20, -30, 40, -50, 60]))
    clock = FakeClock()

    assert shutdown.animate_to_zero(
        robot,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert len(robot.commands) == 60
    assert np.allclose(robot.pose, np.zeros(6))
    assert robot.is_running
    assert not robot.stopped


def test_animate_to_requested_official_home_pose() -> None:
    robot = FakeRobot(np.radians([0, 110, -130, 0, 0, 0]))
    official_home = np.radians([0, 60, -60, 0, 0, 0])
    clock = FakeClock()

    assert shutdown.animate_to_zero(
        robot,
        target_pose=official_home,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert len(robot.commands) == 60
    np.testing.assert_allclose(robot.pose, official_home)
    assert robot.is_running
    assert not robot.stopped


def test_stop_requires_exact_operator_support_ack() -> None:
    robot = FakeRobot(np.radians([5, 4, -3, 2, 1, -1]))
    answers = iter(["yes", "PARKED_SUPPORTED"])

    assert shutdown.home_support_then_stop(
        robot,
        read_line=lambda _prompt: next(answers),
    )
    assert robot.stopped
    assert np.allclose(robot.pose, np.zeros(6))


def test_partial_start_requires_support_before_stop() -> None:
    robot = FakeRobot(np.zeros(6))
    robot.is_running = False
    events: list[str] = []

    def read_line(_prompt: str) -> str:
        events.append("supported")
        return shutdown.SUPPORT_ACK

    original_stop = robot.stop

    def stop() -> None:
        events.append("stopped")
        original_stop()

    robot.stop = stop
    shutdown.support_then_stop(robot, read_line=read_line)

    assert events == ["supported", "stopped"]
    assert robot.stopped


def test_homing_rejects_pose_outside_physical_j4_limit() -> None:
    robot = FakeRobot(np.array([0.0, 0.1, -0.1, 1.35, 0.0, 0.0]))

    assert not shutdown.animate_to_zero(robot)
    assert robot.commands == []
    assert robot.is_running


def test_homing_accepts_and_clips_minor_measured_zero_overshoot() -> None:
    robot = FakeRobot(np.array([0.0, 0.0, 0.0075, 0.0, 0.0, 0.0]))
    clock = FakeClock()

    assert shutdown.animate_to_zero(
        robot,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert np.all(robot.commands[0] <= shutdown.PHYSICAL_LIMITS[:, 1])
    assert np.allclose(robot.pose, np.zeros(6))


def test_hardware_runners_have_no_direct_robot_stop_call() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "scripts/a1z_six_axis_test.py",
        "scripts/a1z_coordinated_demo_test.py",
    ):
        tree = ast.parse((root / relative).read_text())
        direct_stops = [
            node
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "stop"
            )
        ]
        assert direct_stops == [], f"{relative} bypasses safe shutdown"
