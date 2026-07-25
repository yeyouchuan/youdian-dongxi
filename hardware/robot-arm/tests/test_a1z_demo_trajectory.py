import numpy as np
import pytest

from simulation import a1z_demo_trajectory as demo


def test_demo_trajectory_respects_strict_limits_and_speed() -> None:
    trajectory = demo.build_demo_trajectory(
        max_speed_rad_s=0.12, sample_hz=50.0
    )

    assert trajectory.positions.shape[1] == 6
    assert np.all(trajectory.positions >= demo.STRICT_LIMITS[:, 0])
    assert np.all(trajectory.positions <= demo.STRICT_LIMITS[:, 1])
    assert np.max(np.abs(trajectory.velocities)) <= 0.12 + 1e-9
    assert np.allclose(
        trajectory.positions[0], np.radians(demo.POSES_DEG["HOME_SAFE"])
    )
    assert np.allclose(
        trajectory.positions[-1], np.radians(demo.POSES_DEG["HOME_SAFE"])
    )


def test_joint4_strict_limit_is_enforced() -> None:
    pose = np.radians(demo.POSES_DEG["HOME_SAFE"])
    pose[3] = 1.40

    with pytest.raises(ValueError, match=r"joints \[4\]"):
        demo.validate_pose("bad_j4", pose)
