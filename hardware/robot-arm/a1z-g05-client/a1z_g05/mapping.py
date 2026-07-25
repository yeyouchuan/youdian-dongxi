"""A1Z <-> G0.5 (so100 embodiment) observation/action mapping.

Coordinate frames
-----------------
A1Z arm frame (official SDK convention)
    - 6 arm joints in RADIANS
    - 1 gripper, normalized 0.0 (closed) .. 1.0 (open)

so100 model frame (what the g05-so101 checkpoint consumes/produces)
    - 6-D vector in DEGREES: 5 arm joints + 1 gripper
    - arm-frame -> model-frame transform:
      ``model = scales * signs * arm_deg + offsets``
      (see experiments/so100/so100_policy_client.py)

DIMENSION MISMATCH (important)
    A1Z has 6 arm DOF; the so100 checkpoint only drives 5 arm DOF + gripper.
    We therefore select 5 of the 6 A1Z joints (``arm_joint_indices``) to feed
    the model, and hold the remaining A1Z joint(s) at their last commanded value
    when converting actions back. This is a PLACEHOLDER mapping intended to be
    calibrated on-device; all parameters live in config.yaml -> mapping.

Everything here is pure numpy and has no dimos / torch dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

RAD2DEG = 180.0 / np.pi
DEG2RAD = np.pi / 180.0
A1Z_SOFT_LIMITS_RAD = np.asarray(
    [
        [-2.094, 2.094],
        [0.0, 3.142],
        [-3.142, 0.0],
        [-1.484, 1.484],
        [-1.484, 1.484],
        [-2.007, 2.007],
    ],
    dtype=np.float32,
)


@dataclass
class MappingConfig:
    """Calibrated A1Z<->so100 affine joint mapping parameters."""

    arm_joint_indices: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    signs: list[float] = field(default_factory=lambda: [1, -1, 1, 1, 1])
    scales: list[float] = field(default_factory=lambda: [1, 1, 1, 1, 1])
    offsets: list[float] = field(default_factory=lambda: [0, 90, 90, 0, 0])
    gripper_deg_open: float = 0.0
    gripper_deg_closed: float = 45.0
    dof: int = 6

    def __post_init__(self) -> None:
        n = len(self.arm_joint_indices)
        if not (len(self.signs) == len(self.scales) == len(self.offsets) == n):
            raise ValueError(
                f"signs ({len(self.signs)}), scales ({len(self.scales)}), and "
                f"offsets ({len(self.offsets)}) "
                f"must match arm_joint_indices ({n})"
            )
        if any(i < 0 or i >= self.dof for i in self.arm_joint_indices):
            raise ValueError(f"arm_joint_indices out of range for dof={self.dof}")
        self._signs = np.asarray(self.signs, dtype=np.float32)
        self._scales = np.asarray(self.scales, dtype=np.float32)
        if not np.all(np.isfinite(self._scales)) or np.any(self._scales <= 0):
            raise ValueError("scales must be finite and positive")
        self._offsets = np.asarray(self.offsets, dtype=np.float32)


class A1ZSo100Mapping:
    """Bidirectional converter between A1Z arm state and so100 model vectors."""

    def __init__(self, cfg: MappingConfig) -> None:
        self.cfg = cfg

    # -- A1Z -> model (observation direction) -------------------------------

    def state_to_model(self, joints_rad: np.ndarray, gripper_norm: float) -> np.ndarray:
        """A1Z proprio -> so100 model-frame 6-vector (degrees, float32)."""
        joints_rad = np.asarray(joints_rad, dtype=np.float32)
        if joints_rad.shape != (self.cfg.dof,):
            raise ValueError(f"expected A1Z state shape ({self.cfg.dof},), got {joints_rad.shape}")
        if not np.all(np.isfinite(joints_rad)) or not np.isfinite(gripper_norm):
            raise ValueError("A1Z state contains NaN or infinity")
        sel_deg = joints_rad[self.cfg.arm_joint_indices] * RAD2DEG
        arm_model = self.cfg._scales * self.cfg._signs * sel_deg + self.cfg._offsets
        grip_model = self._gripper_to_deg(gripper_norm)
        return np.concatenate([arm_model, [grip_model]]).astype(np.float32)

    # -- model -> A1Z (action direction) ------------------------------------

    def model_to_state(
        self, action_model: np.ndarray, prev_joints_rad: np.ndarray
    ) -> tuple[np.ndarray, float]:
        """so100 model-frame action -> (A1Z joints_rad[dof], gripper_norm).

        Joints not present in ``arm_joint_indices`` keep their previous value.
        """
        action_model = np.asarray(action_model, dtype=np.float32)
        expected = len(self.cfg.arm_joint_indices) + 1
        if action_model.shape != (expected,):
            raise ValueError(f"expected model action shape ({expected},), got {action_model.shape}")
        if not np.all(np.isfinite(action_model)):
            raise ValueError("model action contains NaN or infinity")
        prev_joints_rad = np.asarray(prev_joints_rad, dtype=np.float32)
        if prev_joints_rad.shape != (self.cfg.dof,):
            raise ValueError(
                f"expected previous A1Z state shape ({self.cfg.dof},), got {prev_joints_rad.shape}"
            )
        arm_model = action_model[: len(self.cfg.arm_joint_indices)]
        grip_model = float(action_model[len(self.cfg.arm_joint_indices)])

        sel_deg = (
            (arm_model - self.cfg._offsets)
            / self.cfg._scales
            * self.cfg._signs
        )
        sel_rad = sel_deg * DEG2RAD

        joints = np.asarray(prev_joints_rad, dtype=np.float32).copy()
        for slot, joint_idx in enumerate(self.cfg.arm_joint_indices):
            joints[joint_idx] = sel_rad[slot]
        gripper_norm = self._deg_to_gripper(grip_model)
        return joints, gripper_norm

    # -- gripper helpers ----------------------------------------------------

    def _gripper_to_deg(self, gripper_norm: float) -> float:
        return gripper_to_model(
            gripper_norm, self.cfg.gripper_deg_closed, self.cfg.gripper_deg_open
        )

    def _deg_to_gripper(self, grip_deg: float) -> float:
        return model_to_gripper(
            grip_deg, self.cfg.gripper_deg_closed, self.cfg.gripper_deg_open
        )


def gripper_to_model(value: float, closed: float, opened: float) -> float:
    if opened == closed:
        raise ValueError("gripper calibration endpoints must differ")
    return float(closed + np.clip(value, 0.0, 1.0) * (opened - closed))


def model_to_gripper(value: float, closed: float, opened: float) -> float:
    if opened == closed:
        raise ValueError("gripper calibration endpoints must differ")
    return float(np.clip((value - closed) / (opened - closed), 0.0, 1.0))


def clip_step(target_rad: np.ndarray, current_rad: np.ndarray, max_step_deg: float) -> np.ndarray:
    """Scale the joint delta so no joint moves more than ``max_step_deg`` per tick."""
    if not np.isfinite(max_step_deg) or max_step_deg <= 0:
        raise ValueError("max_step_deg must be finite and positive")
    target_rad = np.asarray(target_rad, dtype=np.float32)
    current_rad = np.asarray(current_rad, dtype=np.float32)
    max_step_rad = float(max_step_deg) * DEG2RAD
    delta = target_rad - current_rad
    biggest = float(np.max(np.abs(delta))) if delta.size else 0.0
    if biggest <= max_step_rad or biggest == 0.0:
        return target_rad
    return current_rad + delta * (max_step_rad / biggest)


def project_target_to_joint_limits(
    joints_rad: np.ndarray,
    limits_rad: np.ndarray,
    max_overshoot_deg: float,
    ignored_joint_indices: tuple[int, ...] = (),
) -> np.ndarray:
    """Project a small model overshoot to a soft limit; reject a large one."""
    joints = np.asarray(joints_rad, dtype=np.float32)
    limits = np.asarray(limits_rad, dtype=np.float32)
    if joints.ndim != 1 or limits.shape != (joints.size, 2):
        raise ValueError(
            f"joint limits must have shape ({joints.size}, 2), got {limits.shape}"
        )
    if not np.all(np.isfinite(joints)):
        raise ValueError("joint target contains NaN or infinity")
    if (
        not np.isfinite(max_overshoot_deg)
        or max_overshoot_deg < 0
        or max_overshoot_deg > 5
    ):
        raise ValueError("max_overshoot_deg must be finite and in [0, 5]")

    checked = np.ones(joints.size, dtype=bool)
    checked[list(ignored_joint_indices)] = False
    overshoot = np.maximum(
        np.maximum(limits[:, 0] - joints, joints - limits[:, 1]),
        0,
    )
    tolerance = float(max_overshoot_deg) * DEG2RAD
    bad = np.flatnonzero(checked & (overshoot > tolerance))
    if bad.size:
        details = ", ".join(
            f"J{i + 1} overshoot={overshoot[i] * RAD2DEG:.2f}deg"
            for i in bad
        )
        raise ValueError(f"A1Z target exceeds soft limits projection tolerance: {details}")

    projected = joints.copy()
    projected[checked] = np.clip(
        projected[checked],
        limits[checked, 0],
        limits[checked, 1],
    )
    return projected


def validate_joint_limits(
    joints_rad: np.ndarray,
    limits_rad: np.ndarray,
    ignored_joint_indices: tuple[int, ...] = (),
) -> None:
    """Reject non-finite or out-of-range A1Z targets; never silently clamp them."""
    joints = np.asarray(joints_rad, dtype=np.float32)
    limits = np.asarray(limits_rad, dtype=np.float32)
    if joints.ndim != 1 or limits.shape != (joints.size, 2):
        raise ValueError(f"joint limits must have shape ({joints.size}, 2), got {limits.shape}")
    if not np.all(np.isfinite(joints)):
        raise ValueError("joint target contains NaN or infinity")
    checked = np.ones(joints.size, dtype=bool)
    checked[list(ignored_joint_indices)] = False
    bad = np.flatnonzero(
        checked & ((joints < limits[:, 0]) | (joints > limits[:, 1]))
    )
    if bad.size:
        details = ", ".join(
            f"J{i + 1}={joints[i]:.3f} not in [{limits[i, 0]:.3f}, {limits[i, 1]:.3f}]"
            for i in bad
        )
        raise ValueError(f"A1Z target violates soft limits: {details}")


def validate_joint_step(
    joints_rad: np.ndarray,
    current_rad: np.ndarray,
    limits_rad: np.ndarray,
    ignored_joint_indices: tuple[int, ...] = (),
) -> None:
    """Accept an in-limit step or a monotonic step recovering from outside."""
    joints = np.asarray(joints_rad, dtype=np.float32)
    current = np.asarray(current_rad, dtype=np.float32)
    limits = np.asarray(limits_rad, dtype=np.float32)
    if joints.ndim != 1 or current.shape != joints.shape:
        raise ValueError("joint target and current state must have matching 1-D shapes")
    if limits.shape != (joints.size, 2):
        raise ValueError(
            f"joint limits must have shape ({joints.size}, 2), got {limits.shape}"
        )
    if not np.all(np.isfinite(joints)) or not np.all(np.isfinite(current)):
        raise ValueError("joint target or current state contains NaN or infinity")

    checked = np.ones(joints.size, dtype=bool)
    checked[list(ignored_joint_indices)] = False
    below = joints < limits[:, 0]
    above = joints > limits[:, 1]
    recovering_low = below & (current < limits[:, 0]) & (joints > current)
    recovering_high = above & (current > limits[:, 1]) & (joints < current)
    bad = np.flatnonzero(
        checked & (below | above) & ~(recovering_low | recovering_high)
    )
    if bad.size:
        details = ", ".join(f"J{i + 1}" for i in bad)
        raise ValueError(f"A1Z step violates soft limits or moves farther outside: {details}")
