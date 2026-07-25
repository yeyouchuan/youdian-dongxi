import threading

import numpy as np
import pytest

from scripts import a1z_coordinated_demo_test as coordinated


def test_stage_segments_fit_hardware_jump_gate() -> None:
    baseline = np.radians([-14.5, 0.19, -6.39, 37.71, -0.78, -82.5])
    targets = [
        np.radians(coordinated.POSES_DEG[name])
        for name in coordinated.STAGE_NAMES
    ]
    planned = [baseline, *targets, baseline]

    for start, target in zip(planned, planned[1:]):
        coordinated.validate_segment(start, target)


def test_segment_over_35_degrees_is_rejected() -> None:
    start = np.zeros(6)
    target = start.copy()
    target[2] = np.radians(-36)

    with pytest.raises(ValueError, match="joint"):
        coordinated.validate_segment(start, target)


def test_tracking_requires_correct_direction_on_every_active_axis() -> None:
    start = np.zeros(6)
    target = np.radians([10, 8, -12, 2, 0, 0])
    measured = np.radians([6, 5, -7, 0, 0, 0])
    wrong = measured.copy()
    wrong[2] *= -1

    assert coordinated.tracking_passed(start, target, measured)
    assert not coordinated.tracking_passed(start, target, wrong)


def test_tracking_ratios_replay_recorded_dance_home_failure() -> None:
    start = np.radians([-2.13, 0.36, 0.36, -0.03, 1.08, -0.49])
    target = np.radians([-1.42, 20.12, -19.64, -0.02, 0.72, -0.33])
    measured = np.radians([-2.11, 17.85, -5.21, 2.22, 1.13, -0.47])

    ratios = coordinated.tracking_ratios(start, target, measured)

    assert np.isnan(ratios[[0, 3, 4, 5]]).all()
    assert ratios[1] == pytest.approx(0.885, abs=0.001)
    assert ratios[2] == pytest.approx(0.278, abs=0.001)


def test_recorded_high_speed_bow_overshoot_is_safe_to_replan() -> None:
    start = np.radians([2.02, 99.42, -101.19, 6.76, 1.34, -0.54])
    target = np.radians([0.62, 106.76, -121.19, 2.07, 0.41, -0.16])
    measured = np.radians([2.04, 114.06, -118.26, 5.28, 1.3, -0.56])

    assert coordinated.tracking_passed(start, target, measured)


def test_large_tracking_overshoot_is_rejected() -> None:
    start = np.zeros(6)
    target = np.radians([10, 0, 0, 0, 0, 0])
    measured = np.radians([25, 0, 0, 0, 0, 0])

    assert not coordinated.tracking_passed(start, target, measured)


def test_final_home_pose_can_reach_goal_despite_small_axis_ratios() -> None:
    target = np.radians([0.0, 60.0, -60.0, 0.0, 0.0, 0.0])
    measured = np.radians([1.19, 62.0, -56.95, 3.29, 1.26, -0.03])

    assert coordinated.target_reached(target, measured)


def test_original_home_failure_remains_outside_goal_tolerance() -> None:
    target = np.radians([-1.42, 20.12, -19.64, -0.02, 0.72, -0.33])
    measured = np.radians([-2.11, 17.85, -5.21, 2.22, 1.13, -0.47])

    assert not coordinated.target_reached(target, measured)


def test_move_accepts_measured_pose_inside_goal_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = np.radians([1.19, 55.72, -50.28, 4.38, 1.26, -0.03])
    target = np.radians([0.0, 60.0, -60.0, 0.0, 0.0, 0.0])
    measured = np.radians([1.19, 62.0, -56.95, 3.29, 1.26, -0.03])

    class FakeRobot:
        is_running = True

        def __init__(self) -> None:
            self.moved = False

        def get_joint_pos(self) -> np.ndarray:
            return measured if self.moved else start

        def get_joint_state(self) -> dict[str, np.ndarray]:
            return {
                "temp_mos": np.full(6, 30.0),
                "eff": np.zeros(6),
                "error_codes": np.zeros(6),
            }

        def command_joint_pos(self, _pose: np.ndarray) -> None:
            pass

        def move_joints(self, _target: np.ndarray, **_kwargs: object) -> None:
            self.moved = True

    monkeypatch.setattr(coordinated.time, "sleep", lambda _seconds: None)
    robot = FakeRobot()

    result = coordinated.move_and_verify(
        robot,
        "DANCE_home_4",
        target,
        0.03,
        threading.Event(),
    )

    np.testing.assert_allclose(result, measured)


def test_joint4_target_keeps_strict_margin() -> None:
    target = np.radians(coordinated.POSES_DEG["AIR_PICK_PRE"])
    coordinated.strict_validate_target("AIR_PICK_PRE", target)
    target[3] = 1.25

    with pytest.raises(ValueError, match=r"joints \[4\]"):
        coordinated.strict_validate_target("bad_j4", target)


def test_adaptive_step_is_below_hardware_segment_gate() -> None:
    current = np.radians([0, 5, -20, 30, 0, -70])
    goal = np.radians([-12, 0, -65, 39, 0, -82])
    delta = goal - current
    scale = min(
        1.0,
        coordinated.ADAPTIVE_STEP_RAD / np.max(np.abs(delta)),
    )
    target = current + scale * delta

    coordinated.validate_segment(current, target)
    assert np.max(np.abs(target - current)) <= coordinated.ADAPTIVE_STEP_RAD


def test_wake_only_stage_excludes_high_pose() -> None:
    wake_only = ("WAKE_LOOK",)

    assert wake_only[0] in coordinated.POSES_DEG
    assert "AIR_PICK_PRE" not in wake_only
