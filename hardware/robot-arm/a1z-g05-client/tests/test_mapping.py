import numpy as np
import pytest

from a1z_g05.mapping import A1ZSo100Mapping, MappingConfig, validate_joint_limits


def mapping() -> A1ZSo100Mapping:
    return A1ZSo100Mapping(
        MappingConfig(
            arm_joint_indices=[0, 1, 2, 3, 4],
            signs=[1, -1, 1, 1, 1],
            offsets=[0, 90, 90, 0, 0],
            gripper_deg_open=10,
            gripper_deg_closed=50,
            dof=6,
        )
    )


def test_official_gripper_convention_round_trips() -> None:
    mapper = mapping()
    joints = np.zeros(6, dtype=np.float32)

    closed = mapper.state_to_model(joints, 0.0)
    opened = mapper.state_to_model(joints, 1.0)

    assert closed[-1] == pytest.approx(50)
    assert opened[-1] == pytest.approx(10)
    _, closed_norm = mapper.model_to_state(closed, joints)
    _, open_norm = mapper.model_to_state(opened, joints)
    assert closed_norm == pytest.approx(0.0)
    assert open_norm == pytest.approx(1.0)


@pytest.mark.parametrize(
    "action",
    [
        np.zeros(5, dtype=np.float32),
        np.zeros(7, dtype=np.float32),
        np.array([0, 0, 0, 0, 0, np.nan], dtype=np.float32),
    ],
)
def test_model_action_must_be_exactly_six_finite_values(action: np.ndarray) -> None:
    with pytest.raises(ValueError):
        mapping().model_to_state(action, np.zeros(6, dtype=np.float32))


def test_joint_limit_violation_is_rejected_not_clipped() -> None:
    limits = np.array([[-1.0, 1.0]] * 6, dtype=np.float32)
    with pytest.raises(ValueError, match="J3"):
        validate_joint_limits(np.array([0, 0, 1.1, 0, 0, 0]), limits)


def test_joint_limit_validation_can_ignore_physically_locked_axis() -> None:
    limits = np.array([[-1.0, 1.0]] * 6, dtype=np.float32)
    validate_joint_limits(
        np.array([0, 0, 0, 1.2, 0, 0]), limits, ignored_joint_indices=(3,)
    )


def test_joint_mapping_scale_round_trips_and_reduces_motion() -> None:
    mapper = A1ZSo100Mapping(
        MappingConfig(
            arm_joint_indices=[0, 1, 2, 4, 5],
            signs=[1, -1, 1, 1, 1],
            scales=[2, 2, 2, 2, 2],
            offsets=[0, 90, 90, 0, 0],
        )
    )
    start = np.zeros(6, dtype=np.float32)
    action = mapper.state_to_model(start, 0.5)
    action[0] += 10
    target, _ = mapper.model_to_state(action, start)
    assert np.rad2deg(target[0]) == pytest.approx(5)
    assert target[3] == 0
