from pathlib import Path

import numpy as np
import pytest

from scripts import a1z_safe_teach_and_play as teach


def trajectory(*frames: tuple[float, list[float]]) -> list[tuple[float, np.ndarray]]:
    return [(timestamp, np.asarray(pose, dtype=np.float64)) for timestamp, pose in frames]


def test_validate_trajectory_accepts_arm_and_gripper_recording() -> None:
    result = teach.validate_trajectory(
        trajectory(
            (0.0, [0, 1.0, -1.0, 0, 0, 0, 1.0]),
            (0.1, [0.01, 1.01, -1.01, 0, 0, 0, 0.9]),
        ),
        speed_factor=0.5,
    )

    assert result.duration_s == pytest.approx(0.1)
    assert result.frames == 2
    assert result.has_gripper is True


def test_validate_trajectory_rejects_non_monotonic_timestamps() -> None:
    with pytest.raises(ValueError, match="timestamps"):
        teach.validate_trajectory(
            trajectory(
                (0.0, [0, 1.0, -1.0, 0, 0, 0]),
                (0.1, [0, 1.0, -1.0, 0, 0, 0]),
                (0.05, [0, 1.0, -1.0, 0, 0, 0]),
            ),
            speed_factor=0.5,
        )


def test_validate_trajectory_rejects_joint_limit_violation() -> None:
    with pytest.raises(ValueError, match="frame 1"):
        teach.validate_trajectory(
            trajectory(
                (0.0, [0, 1.0, -1.0, 0, 0, 0, 1.0]),
                (0.1, [3.0, 1.0, -1.0, 0, 0, 0, 1.0]),
            ),
            speed_factor=0.5,
        )


def test_validate_trajectory_accepts_official_j4_eighty_degrees() -> None:
    teach.validate_trajectory(
        trajectory(
            (0.0, [0, 1.0, -1.0, np.radians(79.0), 0, 0]),
            (0.1, [0, 1.0, -1.0, np.radians(80.0), 0, 0]),
        ),
        speed_factor=0.5,
    )


def test_validate_trajectory_accepts_sdk_limit_noise_tolerance() -> None:
    teach.validate_trajectory(
        trajectory(
            (0.0, [0, 1.0, 0.005, 0, 0, 0]),
            (0.1, [0, 1.0, 0.010, 0, 0, 0]),
        ),
        speed_factor=0.5,
    )


def test_validate_trajectory_accepts_smooth_1_5_rad_s_playback() -> None:
    teach.validate_trajectory(
        trajectory(
            (0.0, [0, 1.0, -1.0, 0, 0, 0]),
            (0.1, [0.15, 1.0, -1.0, 0, 0, 0]),
        ),
        speed_factor=1.0,
    )


def test_validate_trajectory_rejects_excessive_playback_velocity() -> None:
    with pytest.raises(ValueError, match="velocity"):
        teach.validate_trajectory(
            trajectory(
                (0.0, [0, 1.0, -1.0, 0, 0, 0]),
                (0.01, [0.1532, 1.0, -1.0, 0, 0, 0]),
            ),
            speed_factor=1.0,
        )


def test_rejected_recording_is_still_preserved_as_raw_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demo.json"
    unsafe = trajectory(
        (0.0, [0, 1.0, -1.0, 0, 0, 0]),
        (0.01, [0.2, 1.0, -1.0, 0, 0, 0]),
    )

    with pytest.raises(ValueError, match="velocity"):
        teach.persist_recording(unsafe, path, speed_factor=1.0)

    assert not path.exists()
    assert (tmp_path / "demo.raw.json").is_file()


def test_smoothing_retimes_position_step_with_minimum_jerk() -> None:
    raw = trajectory(
        (0.0, [0, 1.0, -1.0, 0, 0, 0, 1.0]),
        (0.02, [0.5, 1.0, -1.0, 0.3, 0, 0, 0.5]),
        (0.04, [0.5, 1.0, -1.0, 0.3, 0, 0, 0.5]),
    )

    smoothed, changed = teach.smooth_trajectory(raw)
    info = teach.validate_trajectory(smoothed, speed_factor=1.0)

    assert changed == 1
    assert len(smoothed) > len(raw)
    np.testing.assert_allclose(smoothed[0][1], raw[0][1])
    np.testing.assert_allclose(smoothed[-1][1], raw[-1][1])
    assert info.max_arm_velocity_rad_s <= (
        teach.MAX_EFFECTIVE_ARM_VELOCITY_RAD_S
    )
    assert info.duration_s > raw[-1][0]


def test_smoothing_leaves_already_slow_trajectory_unchanged() -> None:
    raw = trajectory(
        (0.0, [0, 1.0, -1.0, 0, 0, 0]),
        (0.1, [0.02, 1.0, -1.0, 0, 0, 0]),
    )

    smoothed, changed = teach.smooth_trajectory(raw)

    assert changed == 0
    assert len(smoothed) == len(raw)
    np.testing.assert_allclose(smoothed[-1][1], raw[-1][1])
    assert smoothed[-1][0] == pytest.approx(raw[-1][0])


def test_validate_output_path_stays_inside_recordings_directory(
    tmp_path: Path,
) -> None:
    recordings = tmp_path / "recordings"

    assert teach.validated_recording_path("demo.json", recordings) == (
        recordings / "demo.json"
    )
    with pytest.raises(ValueError, match="inside"):
        teach.validated_recording_path("../outside.json", recordings)


class FakeRobot:
    is_running = True

    def __init__(self) -> None:
        self.moves: list[tuple[np.ndarray, float, float]] = []
        self.stopped = False

    def move_joints(
        self,
        target: np.ndarray,
        *,
        speed: float,
        max_jump_rad: float,
    ) -> None:
        self.moves.append((target.copy(), speed, max_jump_rad))

    def get_joint_pos(self) -> np.ndarray:
        return teach.PARK_POSE.copy()

    def command_joint_pos(self, _target: np.ndarray) -> None:
        return

    def stop(self) -> None:
        self.stopped = True


class FakeMotor:
    def __init__(self) -> None:
        self.disabled = False

    def disable(self) -> None:
        self.disabled = True


class FakeChain:
    def __init__(self) -> None:
        self.disabled = False

    def disable_all(self) -> None:
        self.disabled = True


def test_park_before_supported_disable_uses_slow_continuous_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robot = FakeRobot()
    supported: list[bool] = []
    monkeypatch.setattr(
        teach,
        "wait_for_operator_support",
        lambda: supported.append(True),
    )

    teach.park_before_supported_disable(robot)

    assert len(robot.moves) == 1
    np.testing.assert_allclose(robot.moves[0][0], teach.PARK_POSE)
    assert robot.moves[0][1] == teach.PARK_SPEED_RAD_S
    assert supported == [True]
    assert robot.stopped is True


def test_parking_retries_ctrl_c_before_disabling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robot = FakeRobot()
    attempts = 0

    def interrupted_move(
        target: np.ndarray,
        *,
        speed: float,
        max_jump_rad: float,
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise KeyboardInterrupt
        robot.moves.append((target.copy(), speed, max_jump_rad))

    robot.move_joints = interrupted_move  # type: ignore[method-assign]
    monkeypatch.setattr(teach, "wait_for_operator_support", lambda: None)

    teach.park_before_supported_disable(robot)

    assert attempts == 2
    assert robot.stopped is True


def test_partial_start_requires_support_and_disables_arm_and_gripper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    robot = FakeRobot()
    robot.is_running = False
    robot._motor_chain = FakeChain()
    robot.gripper = FakeMotor()
    supported: list[bool] = []
    monkeypatch.setattr(
        teach,
        "wait_for_operator_support",
        lambda: supported.append(True),
    )

    teach.cleanup_robot(robot, enable_attempted=True)

    assert supported == [True]
    assert robot._motor_chain.disabled is True
    assert robot.gripper.disabled is True


def test_robot_creation_failure_still_closes_hhs_bus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeBus:
        closed = False

        def shutdown(self) -> None:
            self.closed = True

    bus = FakeBus()
    monkeypatch.setattr(teach, "open_hhs_bus", lambda: bus)
    monkeypatch.setattr(
        teach,
        "create_teach_robot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("factory failed")
        ),
    )

    with pytest.raises(RuntimeError, match="factory failed"):
        teach.run(
            "session",
            tmp_path / "unused.json",
            sample_hz=50,
            speed_factor=0.5,
            gravity_factor=0.7,
        )

    assert bus.closed is True
