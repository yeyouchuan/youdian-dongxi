import cv2
import numpy as np
import pytest

from a1z_g05.arm_interface import ArmState
from a1z_g05.controller import InferenceController
from a1z_g05.mapping import A1Z_SOFT_LIMITS_RAD, A1ZSo100Mapping, MappingConfig


class FakeArm:
    dof = 6

    def __init__(self) -> None:
        self.writes = 0
        self.last_joints: np.ndarray | None = None
        self.estopped = False

    def connect(self) -> None:
        return

    def disconnect(self) -> None:
        return

    def read_state(self) -> ArmState:
        return ArmState(np.zeros(6, dtype=np.float32), 1.0)

    def write_joint_positions(self, joints_rad: np.ndarray) -> None:
        self.writes += 1

    def write_state(self, joints_rad: np.ndarray, gripper_norm: float) -> None:
        self.writes += 1
        self.last_joints = np.asarray(joints_rad).copy()

    def write_gripper(self, gripper_norm: float) -> None:
        self.writes += 1

    def home(self) -> None:
        return

    def estop(self) -> None:
        self.estopped = True

    def release_estop(self) -> None:
        self.estopped = False


class ReleaseFailingArm(FakeArm):
    def release_estop(self) -> None:
        raise TimeoutError("release acknowledgement timed out")


class FakeCamera:
    def __init__(self, age: float | None) -> None:
        self.age = age

    def read_rgb_chw(self) -> np.ndarray | None:
        if self.age is None:
            return None
        return np.zeros((3, 8, 8), dtype=np.uint8)

    def frame_age_s(self) -> float | None:
        return self.age


class FakePolicy:
    def __init__(self) -> None:
        self.last_obs = None

    def infer(self, obs):
        self.last_obs = obs
        return {
            "need_obs": True,
            "action": {"right_arm": np.array([0, 90, 90, 0, 0, 50], dtype=np.float32)},
        }


class UnsafePolicy:
    def infer(self, obs):
        return {
            "need_obs": True,
            "action": {"right_arm": np.array([180, 90, 90, 0, 0, 50], dtype=np.float32)},
        }


def controller(
    arm: FakeArm,
    camera: FakeCamera,
    *,
    execute: bool = False,
    max_steps: int | None = None,
):
    mapper = A1ZSo100Mapping(MappingConfig())
    ctl = InferenceController(
        arm=arm,
        camera=camera,
        mapping=mapper,
        server={},
        control={
            "execute_actions": execute,
            "require_camera": True,
            "max_camera_age_s": 0.5,
            "joint_limits_rad": A1Z_SOFT_LIMITS_RAD,
            "max_steps": max_steps,
        },
        camera_cfg={"server_key": "wrist_right", "zero_pad_keys": []},
    )
    ctl._client = FakePolicy()
    ctl.set_task("test")
    return ctl


def test_shadow_mode_never_writes_actions() -> None:
    arm = FakeArm()
    ctl = controller(arm, FakeCamera(0.01))
    ctl._one_tick()
    assert arm.writes == 0
    assert ctl.status().shadow_mode is True


@pytest.mark.parametrize("age", [None, 0.51])
def test_missing_or_stale_camera_fails_closed(age: float | None) -> None:
    ctl = controller(FakeArm(), FakeCamera(age))
    with pytest.raises(RuntimeError, match="camera unavailable"):
        ctl._one_tick()


def test_three_view_file_images_are_sent_to_policy(tmp_path) -> None:
    exterior = tmp_path / "exterior.jpg"
    right = tmp_path / "right.jpg"
    image = np.full((8, 8, 3), 127, dtype=np.uint8)

    assert cv2.imwrite(str(exterior), image)
    assert cv2.imwrite(str(right), image)
    arm = FakeArm()
    mapper = A1ZSo100Mapping(MappingConfig())
    ctl = InferenceController(
        arm=arm,
        camera=FakeCamera(0.01),
        mapping=mapper,
        server={},
        control={"execute_actions": False, "require_camera": True},
        camera_cfg={
            "server_key": "wrist_right",
            "zero_pad_keys": [],
            "dummy_shape": [3, 8, 8],
            "file_images": {
                "exterior": {"path": str(exterior), "max_age_s": 3},
                "wrist_left": {"path": str(right), "max_age_s": 3},
            },
        },
    )
    policy = FakePolicy()
    ctl._client = policy
    ctl.set_task("test all three views")

    ctl._one_tick()

    assert set(policy.last_obs["images"]) == {"exterior", "wrist_left", "wrist_right"}


def test_estop_reaches_arm_backend() -> None:
    arm = FakeArm()
    ctl = controller(arm, FakeCamera(0.01))
    ctl.set_estop(True)
    assert arm.estopped
    ctl.set_estop(False)
    assert not arm.estopped


def test_failed_estop_release_keeps_local_latch() -> None:
    arm = ReleaseFailingArm()
    ctl = controller(arm, FakeCamera(0.01))
    ctl.set_estop(True)
    with pytest.raises(TimeoutError):
        ctl.set_estop(False)
    assert ctl._estop is True


@pytest.mark.parametrize("max_step", [0.0, -1.0, float("inf"), float("nan")])
def test_invalid_step_limit_is_rejected(max_step: float) -> None:
    arm = FakeArm()
    mapper = A1ZSo100Mapping(MappingConfig())
    with pytest.raises(ValueError, match="max_step_deg"):
        InferenceController(
            arm=arm,
            camera=FakeCamera(0.01),
            mapping=mapper,
            server={},
            control={"max_step_deg": max_step},
            camera_cfg={},
        )


def test_joint_limit_override_cannot_widen_official_limits() -> None:
    arm = FakeArm()
    mapper = A1ZSo100Mapping(MappingConfig())
    widened = np.array([[-10.0, 10.0]] * 6)
    with pytest.raises(ValueError, match="official limits"):
        InferenceController(
            arm=arm,
            camera=FakeCamera(0.01),
            mapping=mapper,
            server={},
            control={"joint_limits_rad": widened},
            camera_cfg={},
        )


def test_far_out_of_limit_target_is_rejected_before_step_clipping() -> None:
    arm = FakeArm()
    ctl = controller(arm, FakeCamera(0.01), execute=True)
    ctl._client = UnsafePolicy()
    with pytest.raises(ValueError, match="soft limits"):
        ctl._one_tick()
    assert arm.writes == 0


def test_max_steps_is_enforced_inside_control_loop() -> None:
    arm = FakeArm()
    ctl = controller(arm, FakeCamera(0.01), execute=True, max_steps=1)
    ctl._one_tick()
    ctl._one_tick()
    assert ctl.status().step == 1
    assert arm.writes == 1


def test_small_model_overshoot_is_projected_to_soft_limit_before_step() -> None:
    arm = FakeArm()
    arm.read_state = lambda: ArmState(
        np.deg2rad(
            np.array([-0.16, 13.50, -23.97, 95.81, 72.90, -30.41])
        ).astype(np.float32),
        1.0,
    )
    mapper = A1ZSo100Mapping(
        MappingConfig(
            arm_joint_indices=[0, 1, 2, 4, 5],
            signs=[1, -1, 1, 1, 1],
            scales=[2, 2, 2, 2, 2],
            offsets=[0.32, 117.00, 137.94, -145.80, 60.82],
        )
    )
    ctl = InferenceController(
        arm=arm,
        camera=FakeCamera(0.01),
        mapping=mapper,
        server={},
        control={
            "execute_actions": True,
            "max_step_deg": 2.0,
            "max_target_limit_overshoot_deg": 2.0,
            "locked_joint_indices": [3],
        },
        camera_cfg={"server_key": "wrist_right", "zero_pad_keys": []},
    )
    ctl._client = FakePolicy()
    ctl._client.infer = lambda _obs: {
        "need_obs": False,
        # J5 decodes to 86.4 deg: 1.37 deg beyond the 85.03 deg soft limit.
        "action": {
            "right_arm": np.array(
                [0.32, 90.0, 90.0, 27.0, 0.0, 45.0], dtype=np.float32
            )
        },
    }
    ctl.set_task("close the gripper")

    ctl._one_tick()

    assert arm.writes == 1
    assert arm.last_joints is not None
    assert arm.last_joints[4] <= A1Z_SOFT_LIMITS_RAD[4, 1]


def test_joint_already_outside_limit_recovers_before_policy_inference() -> None:
    arm = FakeArm()
    current_deg = np.array(
        [-3.05, 0.30, -0.27, 16.43, 90.24, -31.66],
        dtype=np.float32,
    )
    arm.read_state = lambda: ArmState(
        np.deg2rad(current_deg).astype(np.float32),
        1.0,
    )
    mapper = A1ZSo100Mapping(
        MappingConfig(
            arm_joint_indices=[0, 1, 2, 4, 5],
            signs=[1, -1, 1, 1, 1],
            scales=[2, 2, 2, 3, 2],
            offsets=[3.44501, 151.34757, 169.43454, -162.80379, 48.56067],
            gripper_deg_open=45.0,
            gripper_deg_closed=0.0,
        )
    )
    ctl = InferenceController(
        arm=arm,
        camera=FakeCamera(0.01),
        mapping=mapper,
        server={},
        control={
            "execute_actions": True,
            "max_step_deg": 2.0,
            "max_target_limit_overshoot_deg": 5.0,
            "locked_joint_indices": [3],
        },
        camera_cfg={"server_key": "wrist_right", "zero_pad_keys": []},
    )
    ctl._client = FakePolicy()
    ctl._client.infer = lambda _obs: pytest.fail(
        "policy must not run until measured joints recover inside soft limits"
    )
    ctl.set_task("recover")

    ctl._one_tick()

    assert arm.last_joints is not None
    assert np.rad2deg(arm.last_joints[4]) < current_deg[4]
    assert ctl.status().step == 0


def test_locked_joint_returns_toward_startup_anchor_instead_of_ratchet_drift() -> None:
    arm = FakeArm()
    states = iter(
        [
            ArmState(
                np.deg2rad(np.array([0, 60, -60, 10, 0, 0], dtype=np.float32)),
                1.0,
            ),
            ArmState(
                np.deg2rad(np.array([0, 60, -60, 30, 0, 0], dtype=np.float32)),
                1.0,
            ),
        ]
    )
    arm.read_state = lambda: next(states)
    ctl = InferenceController(
        arm=arm,
        camera=FakeCamera(0.01),
        mapping=A1ZSo100Mapping(MappingConfig()),
        server={},
        control={
            "execute_actions": True,
            "max_step_deg": 2.0,
            "locked_joint_indices": [3],
        },
        camera_cfg={"server_key": "wrist_right", "zero_pad_keys": []},
    )
    ctl._client = FakePolicy()
    ctl.set_task("test locked-joint anchor")

    ctl._one_tick()
    ctl._one_tick()

    assert arm.last_joints is not None
    assert np.rad2deg(arm.last_joints[3]) < 30.0
