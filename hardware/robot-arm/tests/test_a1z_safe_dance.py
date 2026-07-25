from types import SimpleNamespace

import numpy as np
import pytest

from scripts import a1z_safe_dance as safe_dance


class FakeContinuousRobot:
    is_running = True

    def __init__(self) -> None:
        self.pose = np.zeros(6)
        self.moves: list[tuple[np.ndarray, float, np.ndarray]] = []

    def get_joint_pos(self) -> np.ndarray:
        return self.pose.copy()

    def get_joint_state(self) -> dict[str, np.ndarray]:
        return {
            "temp_mos": np.full(6, 30.0),
            "eff": np.zeros(6),
            "error_codes": np.zeros(6),
        }

    def command_joint_pos(self, target: np.ndarray) -> None:
        self.pose = target.copy()

    def move_joints(
        self,
        target: np.ndarray,
        *,
        speed: float,
        kp: np.ndarray,
        **_kwargs: object,
    ) -> None:
        self.moves.append((target.copy(), speed, kp.copy()))
        self.pose = target.copy()


def test_pinned_official_default_dance_passes_strict_limits() -> None:
    official = safe_dance.load_official_dance()
    order = tuple(official.DEFAULT_ORDER)

    safe_dance.validate_choreography(official, order)

    assert order == ("salute", "wave", "nod", "reach", "bow")
    assert np.isclose(
        official.POSES["nod_a"][3],
        np.radians(50),
    )


def test_choreography_rejects_unknown_move() -> None:
    official = safe_dance.load_official_dance()

    with pytest.raises(ValueError, match="unknown"):
        safe_dance.validate_choreography(official, ("not-a-move",))


def test_safety_proxy_caps_official_speed() -> None:
    robot = FakeContinuousRobot()
    kp = np.array([30.0, 30.0, 60.0, 30.0, 5.0, 5.0])
    proxy = safe_dance.SafetyGatedDanceRobot(
        robot,
        SimpleNamespace(is_set=lambda: False),
        max_speed_rad_s=0.05,
        kp=kp,
    )
    target = np.radians([0, 60, -60, 0, 0, 0])
    proxy.register_poses({"home": target})

    proxy.move_joints(target, speed=0.9)

    assert len(robot.moves) == 1
    assert robot.moves[0][1] == 0.05
    np.testing.assert_array_equal(robot.moves[0][2], kp)


def test_safety_proxy_forwards_official_base_speed() -> None:
    robot = FakeContinuousRobot()
    proxy = safe_dance.SafetyGatedDanceRobot(
        robot,
        SimpleNamespace(is_set=lambda: False),
        max_speed_rad_s=safe_dance.MAX_DANCE_POSE_SPEED_RAD_S,
        kp=np.array([30.0, 30.0, 60.0, 30.0, 5.0, 5.0]),
    )
    target = np.radians([0, 60, -60, 0, 0, 0])

    proxy.move_joints(target, speed=0.6)

    assert len(robot.moves) == 1
    assert robot.moves[0][1] == 0.6


def test_safety_proxy_preserves_official_wave_multiplier() -> None:
    robot = FakeContinuousRobot()
    proxy = safe_dance.SafetyGatedDanceRobot(
        robot,
        SimpleNamespace(is_set=lambda: False),
        max_speed_rad_s=safe_dance.MAX_DANCE_POSE_SPEED_RAD_S,
        kp=np.array([30.0, 60.0, 60.0, 30.0, 5.0, 5.0]),
    )
    target = np.radians([-80, 60, -60, 0, 60, 90])

    proxy.move_joints(target, speed=0.9)

    assert len(robot.moves) == 1
    assert robot.moves[0][1] == 0.9


def test_official_pose_uses_one_continuous_six_axis_trajectory() -> None:
    robot = FakeContinuousRobot()
    kp = np.array([30.0, 60.0, 60.0, 30.0, 5.0, 5.0])
    proxy = safe_dance.SafetyGatedDanceRobot(
        robot,
        SimpleNamespace(is_set=lambda: False),
        max_speed_rad_s=0.6,
        kp=kp,
    )
    target = np.radians([30, 35, -80, 0, 80, 90])

    proxy.move_joints(target, speed=0.6)

    assert len(robot.moves) == 1
    np.testing.assert_allclose(robot.moves[0][0], target)
    assert robot.moves[0][1] == 0.6
    np.testing.assert_array_equal(robot.moves[0][2], kp)


def test_dance_kp_can_raise_j2_and_j3_independently() -> None:
    kp = safe_dance.build_dance_kp(j2_kp=60.0, j3_kp=55.0)

    np.testing.assert_array_equal(
        kp,
        [30.0, 60.0, 55.0, 30.0, 5.0, 5.0],
    )


def test_dance_shutdown_uses_official_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official_home = np.radians([0, 60, -60, 0, 0, 0])
    captured: list[np.ndarray] = []

    def fake_shutdown(
        _robot: object,
        *,
        parking_pose: np.ndarray,
    ) -> bool:
        captured.append(parking_pose.copy())
        return True

    monkeypatch.setattr(safe_dance, "home_support_then_stop", fake_shutdown)

    safe_dance.shutdown_dance(
        SimpleNamespace(),
        SimpleNamespace(POSES={"home": official_home}),
    )

    np.testing.assert_allclose(captured, [official_home])


def test_gripper_is_disabled_for_default_dance() -> None:
    proxy = safe_dance.SafetyGatedDanceRobot(
        SimpleNamespace(),
        SimpleNamespace(),
        max_speed_rad_s=0.05,
        kp=np.array([30.0, 30.0, 60.0, 30.0, 5.0, 5.0]),
    )

    with pytest.raises(RuntimeError, match="disabled"):
        proxy.command_gripper(1.0)
