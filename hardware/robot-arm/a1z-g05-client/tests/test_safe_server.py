import numpy as np
import pytest

from a1z_g05.safe_server import (
    SAFE_DEFAULT_KD,
    SAFE_DEFAULT_KP,
    acquire_instance_lock,
    build_tool_pose_data,
    build_watchdog_hold_target,
    preserve_locked_joint_targets,
    validate_blocking_move_execution,
    validate_blocking_move_target,
    validate_cartesian_delta,
    validate_cartesian_execution,
    validate_cartesian_solution,
    validate_motion_health,
    validate_stream_target,
)

LIMITS = [
    (-2.094, 2.094),
    (0.0, 3.142),
    (-3.142, 0.0),
    (-1.484, 1.484),
    (-1.484, 1.484),
    (-2.007, 2.007),
]


def test_safe_server_instance_lock_rejects_second_daemon(tmp_path) -> None:
    lock_path = tmp_path / "safe-server.lock"
    first = acquire_instance_lock(lock_path)
    try:
        with pytest.raises(RuntimeError, match="already running"):
            acquire_instance_lock(lock_path)
    finally:
        first.close()


def test_locked_j4_uses_low_stiffness_hold_instead_of_free_drift() -> None:
    assert SAFE_DEFAULT_KP[3] > 0
    assert SAFE_DEFAULT_KP[3] < SAFE_DEFAULT_KP[0]
    assert SAFE_DEFAULT_KD[3] > 0


def test_stream_preserves_server_locked_target_instead_of_client_measurement() -> None:
    requested = np.array([0, 60, -60, 10.7, 0, 0], dtype=np.float64)
    server_command = np.array([0, 60, -60, 0, 0, 0], dtype=np.float64)

    result = preserve_locked_joint_targets(
        requested, server_command, locked_joint_indices=(3,)
    )

    np.testing.assert_allclose(result, [0, 60, -60, 0, 0, 0])


def test_watchdog_hold_preserves_locked_server_target_without_ratcheting_drift() -> None:
    measured = np.deg2rad(np.array([1, 2, 3, 73, 5, 6], dtype=np.float64))
    command = np.deg2rad(np.array([10, 20, 30, 40, 50, 60], dtype=np.float64))

    result = build_watchdog_hold_target(measured, command, (3,))

    np.testing.assert_allclose(
        np.rad2deg(result),
        np.array([1, 2, 3, 40, 5, 6], dtype=np.float64),
    )


def test_stream_target_accepts_small_finite_step() -> None:
    result = validate_stream_target([1, 61, -61, 0, 0, 0], [0, 60, -60, 0, 0, 0], LIMITS, 3)
    np.testing.assert_allclose(result, np.deg2rad([1, 61, -61, 0, 0, 0]))


@pytest.mark.parametrize(
    "target",
    [
        [0, 60, -60, 0, 0, float("nan")],
        [0, 60, -60, 0, 0],
        [0, -1, -60, 0, 0, 0],
        [0, 60, 1, 0, 0, 0],
        [10, 60, -60, 0, 0, 0],
    ],
)
def test_stream_target_rejects_invalid_or_unsafe_input(target: list[float]) -> None:
    with pytest.raises(ValueError):
        validate_stream_target(target, np.array([0, 60, -60, 0, 0, 0]), LIMITS, 3)


def test_stream_target_allows_locked_joint_outside_soft_limit() -> None:
    current = np.array([0, 60, -60, 95, 0, 0], dtype=np.float64)
    result = validate_stream_target(
        current, current, LIMITS, 3, locked_joint_indices=(3,)
    )
    np.testing.assert_allclose(np.rad2deg(result), current)


def test_stream_target_rejects_locked_joint_motion() -> None:
    current = np.array([0, 60, -60, 95, 0, 0], dtype=np.float64)
    with pytest.raises(ValueError, match="locked J4"):
        validate_stream_target(
            [0, 60, -60, 95.2, 0, 0],
            current,
            LIMITS,
            3,
            locked_joint_indices=(3,),
        )


def test_stream_target_allows_small_step_back_inside_from_outside_limit() -> None:
    current = np.array([0, 60, -60, 0, 90, 0], dtype=np.float64)
    result = validate_stream_target(
        [0, 60, -60, 0, 89, 0], current, LIMITS, 3
    )
    assert np.rad2deg(result[4]) == pytest.approx(89)


def test_stream_target_rejects_step_farther_outside_limit() -> None:
    current = np.array([0, 60, -60, 0, 90, 0], dtype=np.float64)
    with pytest.raises(ValueError, match="J5"):
        validate_stream_target(
            [0, 60, -60, 0, 91, 0], current, LIMITS, 3
        )


def test_blocking_move_preserves_locked_joint_from_measured_state() -> None:
    result = validate_blocking_move_target(
        [0, 60, -60, 0, 0, 0],
        [-1, 12, -3, 9.5, 1, -2],
        LIMITS,
        locked_joint_indices=(3,),
    )

    np.testing.assert_allclose(
        np.rad2deg(result),
        [0, 60, -60, 9.5, 0, 0],
    )


def test_blocking_move_rejects_out_of_limit_movable_joint() -> None:
    with pytest.raises(ValueError, match="J2"):
        validate_blocking_move_target(
            [0, -1, -60, 0, 0, 0],
            [0, 60, -60, 9.5, 0, 0],
            LIMITS,
            locked_joint_indices=(3,),
        )


def test_blocking_move_rejects_command_completion_without_measured_arrival() -> None:
    target = np.deg2rad([0, 60, -60, 7.4, 0, 0])
    measured = np.deg2rad([-2.04, 60.38, -56.55, 10.63, 0.86, 0.60])

    with pytest.raises(RuntimeError, match=r"J3 error=3\.45deg"):
        validate_blocking_move_execution(
            target,
            measured,
            tolerance_deg=1.5,
        )


def test_blocking_move_accepts_measured_pose_inside_arrival_tolerance() -> None:
    target = np.deg2rad([0, 60, -60, 7.4, 0, 0])
    measured = np.deg2rad([-0.8, 60.4, -59.1, 8.2, 0.5, -0.3])

    error_deg = validate_blocking_move_execution(
        target,
        measured,
        tolerance_deg=1.5,
    )

    np.testing.assert_allclose(
        error_deg,
        [0.8, 0.4, 0.9, 0.8, 0.5, 0.3],
        atol=1e-9,
    )


def test_motion_health_rejects_motor_fault_or_over_temperature() -> None:
    validate_motion_health(
        [0, 0, 0, 1, 1, 1],
        [39, 43, 57, 37, 28, 26],
        [31, 34, 56.5, 35, 35, 35],
    )

    with pytest.raises(RuntimeError, match="motor error codes"):
        validate_motion_health(
            [0, 0, 0, 9, 1, 1],
            [39, 43, 57, 37, 28, 26],
            [31, 34, 56.5, 35, 35, 35],
        )
    with pytest.raises(RuntimeError, match=r"MOS temperature 70\.0"):
        validate_motion_health(
            [0, 0, 0, 1, 1, 1],
            [39, 43, 70, 37, 28, 26],
            [31, 34, 56.5, 35, 35, 35],
        )
    with pytest.raises(RuntimeError, match=r"rotor temperature 90\.0"):
        validate_motion_health(
            [0, 0, 0, 1, 1, 1],
            [39, 43, 57, 37, 28, 26],
            [31, 34, 90, 35, 35, 35],
        )


def test_tool_pose_data_exposes_current_base_from_arm_link6() -> None:
    class FakeKinematics:
        def fk(self, joints):
            np.testing.assert_allclose(joints, np.deg2rad([0, 60, -60, 7, 0, 0]))
            return np.array(
                [
                    [1.0, 0.0, 0.0, 0.40],
                    [0.0, 1.0, 0.0, 0.10],
                    [0.0, 0.0, 1.0, 0.30],
                    [0.0, 0.0, 0.0, 1.0],
                ]
            )

    data = build_tool_pose_data(
        FakeKinematics(),
        np.deg2rad([0, 60, -60, 7, 0, 0]),
    )

    assert data["tcp_m"] == [0.4, 0.1, 0.3]
    assert data["base_from_tool"][3] == [0.0, 0.0, 0.0, 1.0]


def test_cartesian_delta_accepts_one_bounded_translation_waypoint() -> None:
    result = validate_cartesian_delta([0.01, -0.005, 0.002])

    np.testing.assert_allclose(result, [0.01, -0.005, 0.002])


@pytest.mark.parametrize(
    "delta",
    [
        [0, 0, 0],
        [0.0201, 0, 0],
        [0.02, 0.02, 0.02],
        [0.01, 0.01],
        [0.01, float("nan"), 0],
    ],
)
def test_cartesian_delta_rejects_invalid_or_oversized_waypoint(delta) -> None:
    with pytest.raises(ValueError):
        validate_cartesian_delta(delta)


def test_cartesian_solution_accepts_small_in_limit_ik_result() -> None:
    current = np.deg2rad([0, 60, -60, 3, 0, 0])
    target = np.deg2rad([2, 62, -63, 3, 4, -2])

    result = validate_cartesian_solution(
        target,
        current,
        LIMITS,
        locked_joint_indices=(3,),
    )

    np.testing.assert_allclose(result, target)


@pytest.mark.parametrize(
    ("target_deg", "match"),
    [
        ([0, 60, -60, 3.2, 0, 0], "locked J4"),
        ([9, 60, -60, 3, 0, 0], "jump J1"),
        ([0, 60, 1, 3, 0, 0], "soft limits at J3"),
    ],
)
def test_cartesian_solution_rejects_unsafe_ik_result(target_deg, match) -> None:
    current = np.deg2rad([0, 60, -60, 3, 0, 0])

    with pytest.raises(ValueError, match=match):
        validate_cartesian_solution(
            np.deg2rad(target_deg),
            current,
            LIMITS,
            locked_joint_indices=(3,),
        )


def test_cartesian_execution_accepts_matching_measured_motion() -> None:
    requested = np.array([0.01, 0, 0])
    achieved = validate_cartesian_execution(
        requested,
        [0.2, 0.1, 0.3],
        [0.209, 0.1, 0.3],
        np.deg2rad([0, 60, -60, 4, 0, 0]),
        np.deg2rad([1, 60, -60, 4.2, 0, 0]),
        locked_joint_indices=(3,),
    )

    np.testing.assert_allclose(achieved, [0.009, 0, 0])


@pytest.mark.parametrize(
    ("after_tcp", "after_joints", "match"),
    [
        ([0.19, 0.1, 0.3], [0, 60, -60, 4, 0, 0], "opposite"),
        ([0.202, 0.1, 0.3], [0, 60, -60, 4, 0, 0], "TCP error"),
        ([0.209, 0.1, 0.3], [0, 60, -60, 5.1, 0, 0], "locked J4"),
    ],
)
def test_cartesian_execution_rejects_wrong_motion_or_locked_drift(
    after_tcp,
    after_joints,
    match,
) -> None:
    with pytest.raises(RuntimeError, match=match):
        validate_cartesian_execution(
            [0.01, 0, 0],
            [0.2, 0.1, 0.3],
            after_tcp,
            np.deg2rad([0, 60, -60, 4, 0, 0]),
            np.deg2rad(after_joints),
            locked_joint_indices=(3,),
        )
