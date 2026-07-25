import numpy as np
import pytest

from a1z_g05.mapping import MappingConfig
from a1z_g05.retargeting import KinematicRetargeter, RetargetingConfig


class CartesianFakeKinematics:
    nq = 6

    def __init__(self, converges: bool = True) -> None:
        self.converges = converges

    def fk(self, q: np.ndarray) -> np.ndarray:
        pose = np.eye(4)
        pose[:3, 3] = q[:3]
        return pose

    def ik(self, target: np.ndarray, initial: np.ndarray) -> tuple[bool, np.ndarray]:
        result = np.asarray(initial, dtype=np.float64).copy()
        result[:3] = target[:3, 3]
        return self.converges, result


def retargeter(*, a1z_converges: bool = True) -> KinematicRetargeter:
    base = np.eye(4)
    base[:3, 3] = [0.5, -0.25, 0.1]
    return KinematicRetargeter(
        RetargetingConfig(
            model=MappingConfig(
                signs=[1, 1, 1, 1, 1],
                offsets=[0, 0, 0, 0, 0],
                gripper_deg_open=10,
                gripper_deg_closed=50,
            ),
            position_scale=2.0,
            base_transform=base,
            tool_transform=np.eye(4),
        ),
        CartesianFakeKinematics(),
        CartesianFakeKinematics(converges=a1z_converges),
    )


def test_model_action_uses_fk_frame_transform_and_a1z_ik() -> None:
    model_action = np.array([10, 20, 30, 0, 0, 10], dtype=np.float32)
    joints, gripper = retargeter().model_to_state(model_action, np.zeros(6))
    expected_xyz = np.array([0.5, -0.25, 0.1]) + 2 * np.deg2rad([10, 20, 30])
    np.testing.assert_allclose(joints[:3], expected_xyz, atol=1e-6)
    assert gripper == pytest.approx(1.0)


def test_observation_direction_inverts_calibrated_frame() -> None:
    mapper = retargeter()
    model_action = np.array([10, 20, 30, 0, 0, 50], dtype=np.float32)
    a1z_joints, _ = mapper.model_to_state(model_action, np.zeros(6))
    reconstructed = mapper.state_to_model(a1z_joints, 0.0)
    np.testing.assert_allclose(reconstructed, model_action, atol=1e-5)


def test_failed_a1z_ik_rejects_action() -> None:
    with pytest.raises(ValueError, match="A1Z IK"):
        retargeter(a1z_converges=False).model_to_state(np.zeros(6), np.zeros(6))


@pytest.mark.parametrize(
    "bad_transform",
    [
        np.full((4, 4), np.nan),
        np.diag([2.0, 1.0, 1.0, 1.0]),
        np.diag([-1.0, 1.0, 1.0, 1.0]),
        np.vstack([np.eye(3, 4), [0.0, 0.0, 0.0, 2.0]]),
    ],
)
def test_retargeting_rejects_non_se3_transforms(bad_transform: np.ndarray) -> None:
    with pytest.raises(ValueError):
        RetargetingConfig(
            model=MappingConfig(),
            position_scale=1.0,
            base_transform=bad_transform,
            tool_transform=np.eye(4),
        )
