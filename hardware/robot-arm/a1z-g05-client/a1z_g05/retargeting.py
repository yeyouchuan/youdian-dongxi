"""FK/IK retargeting between the SO100 training body and Galaxea A1Z."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from a1z_g05.mapping import MappingConfig, gripper_to_model, model_to_gripper

RAD2DEG = 180.0 / np.pi
DEG2RAD = np.pi / 180.0


class Kinematics(Protocol):
    nq: int

    def fk(self, q: np.ndarray) -> np.ndarray: ...
    def ik(self, target: np.ndarray, initial: np.ndarray) -> tuple[bool, np.ndarray]: ...


class PinocchioKinematics:
    """Small Pinocchio adapter loaded lazily on the robot host."""

    def __init__(
        self,
        urdf_path: str,
        end_effector_frame: str,
        locked_joint_indices: list[int] | None = None,
    ) -> None:
        import pinocchio

        path = Path(urdf_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"URDF not found: {path}")
        self._pin = pinocchio
        self._model = pinocchio.buildModelFromUrdf(str(path))
        self._data = self._model.createData()
        self._frame_id = self._model.getFrameId(end_effector_frame)
        if self._frame_id >= self._model.nframes:
            raise ValueError(f"frame {end_effector_frame!r} not found in {path}")
        self.nq = self._model.nq
        self._locked_joint_indices = tuple(sorted(set(locked_joint_indices or [])))
        if any(index < 0 or index >= self.nq for index in self._locked_joint_indices):
            raise ValueError(
                f"locked joint indices must be between 0 and {self.nq - 1}"
            )
        if self._model.nq != self._model.nv:
            raise ValueError("locked-joint IK requires nq == nv")
        self._active_velocity_indices = tuple(
            index
            for index in range(self._model.nv)
            if index not in self._locked_joint_indices
        )
        if not self._active_velocity_indices:
            raise ValueError("at least one joint must remain active")

    def fk(self, q: np.ndarray) -> np.ndarray:
        q = np.asarray(q, dtype=np.float64)
        if q.shape != (self.nq,):
            raise ValueError(f"FK expected shape ({self.nq},), got {q.shape}")
        self._pin.forwardKinematics(self._model, self._data, q)
        self._pin.updateFramePlacements(self._model, self._data)
        pose = self._data.oMf[self._frame_id]
        result = np.eye(4)
        result[:3, :3] = pose.rotation
        result[:3, 3] = pose.translation
        return result

    def ik(self, target: np.ndarray, initial: np.ndarray) -> tuple[bool, np.ndarray]:
        initial = np.asarray(initial, dtype=np.float64)
        q = np.clip(
            initial,
            self._model.lowerPositionLimit,
            self._model.upperPositionLimit,
        )
        locked_values = initial[list(self._locked_joint_indices)].copy()
        q[list(self._locked_joint_indices)] = locked_values
        desired = self._pin.SE3(target[:3, :3], target[:3, 3])
        for _ in range(300):
            self._pin.forwardKinematics(self._model, self._data, q)
            self._pin.updateFramePlacements(self._model, self._data)
            current = self._data.oMf[self._frame_id]
            error = self._pin.log6(current.actInv(desired)).vector
            if np.linalg.norm(error[:3]) <= 1e-3 and np.linalg.norm(error[3:]) <= 1e-2:
                return True, q
            jacobian = self._pin.computeFrameJacobian(
                self._model, self._data, q, self._frame_id, self._pin.LOCAL
            )
            active = list(self._active_velocity_indices)
            reduced_jacobian = jacobian[:, active]
            lhs = (
                reduced_jacobian.T @ reduced_jacobian
                + 1e-5 * np.eye(len(active))
            )
            reduced_velocity = np.linalg.solve(
                lhs, reduced_jacobian.T @ error
            )
            velocity = np.zeros(self._model.nv, dtype=np.float64)
            velocity[active] = reduced_velocity
            q = self._pin.integrate(self._model, q, velocity * 0.05)
            q = np.clip(q, self._model.lowerPositionLimit, self._model.upperPositionLimit)
            q[list(self._locked_joint_indices)] = locked_values
        return False, q

    def ik_position(
        self,
        target_position: np.ndarray,
        initial: np.ndarray,
    ) -> tuple[bool, np.ndarray]:
        """Solve TCP position only, preserving locked joints and minimal joint motion."""
        target = np.asarray(target_position, dtype=np.float64)
        initial = np.asarray(initial, dtype=np.float64)
        if target.shape != (3,) or not np.all(np.isfinite(target)):
            raise ValueError("position IK target must be a finite xyz vector")
        if initial.shape != (self.nq,) or not np.all(np.isfinite(initial)):
            raise ValueError(f"position IK initial state must have shape ({self.nq},)")

        q = np.clip(
            initial,
            self._model.lowerPositionLimit,
            self._model.upperPositionLimit,
        )
        locked_values = initial[list(self._locked_joint_indices)].copy()
        q[list(self._locked_joint_indices)] = locked_values
        active = list(self._active_velocity_indices)
        for _ in range(300):
            self._pin.forwardKinematics(self._model, self._data, q)
            self._pin.updateFramePlacements(self._model, self._data)
            current = self._data.oMf[self._frame_id]
            error = current.rotation.T @ (target - current.translation)
            if np.linalg.norm(error) <= 1e-3:
                return True, q
            jacobian = self._pin.computeFrameJacobian(
                self._model,
                self._data,
                q,
                self._frame_id,
                self._pin.LOCAL,
            )[:3, active]
            lhs = jacobian @ jacobian.T + 1e-5 * np.eye(3)
            reduced_velocity = jacobian.T @ np.linalg.solve(lhs, error)
            velocity = np.zeros(self._model.nv, dtype=np.float64)
            velocity[active] = reduced_velocity
            q = self._pin.integrate(self._model, q, velocity * 0.1)
            q = np.clip(q, self._model.lowerPositionLimit, self._model.upperPositionLimit)
            q[list(self._locked_joint_indices)] = locked_values
        return False, q


@dataclass
class RetargetingConfig:
    model: MappingConfig
    position_scale: float
    base_transform: np.ndarray
    tool_transform: np.ndarray

    def __post_init__(self) -> None:
        self.base_transform = np.asarray(self.base_transform, dtype=np.float64)
        self.tool_transform = np.asarray(self.tool_transform, dtype=np.float64)
        for name, transform in (
            ("base_transform", self.base_transform),
            ("tool_transform", self.tool_transform),
        ):
            if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
                raise ValueError(f"{name} must be a finite 4x4 matrix")
            if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-7):
                raise ValueError(f"{name} must have homogeneous bottom row [0, 0, 0, 1]")
            rotation = transform[:3, :3]
            if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6):
                raise ValueError(f"{name} rotation must be orthonormal")
            if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6):
                raise ValueError(f"{name} rotation determinant must be +1")
        if not np.isfinite(self.position_scale) or self.position_scale <= 0:
            raise ValueError("retargeting position_scale must be positive")


class KinematicRetargeter:
    """Map observations and actions through FK → calibrated frame → IK."""

    def __init__(
        self,
        cfg: RetargetingConfig,
        so100: Kinematics,
        a1z: Kinematics,
    ) -> None:
        self.cfg = cfg
        self._so100 = so100
        self._a1z = a1z
        self._last_so_q = np.zeros(so100.nq, dtype=np.float64)

    def _so_to_a1z_pose(self, so_pose: np.ndarray) -> np.ndarray:
        base = self.cfg.base_transform
        tool = self.cfg.tool_transform
        result = np.eye(4)
        result[:3, :3] = base[:3, :3] @ so_pose[:3, :3] @ tool[:3, :3]
        result[:3, 3] = base[:3, 3] + base[:3, :3] @ (
            self.cfg.position_scale * so_pose[:3, 3]
            + so_pose[:3, :3] @ tool[:3, 3]
        )
        return result

    def _a1z_to_so_pose(self, a1z_pose: np.ndarray) -> np.ndarray:
        base = self.cfg.base_transform
        tool = self.cfg.tool_transform
        result = np.eye(4)
        result[:3, :3] = base[:3, :3].T @ a1z_pose[:3, :3] @ tool[:3, :3].T
        result[:3, 3] = (
            base[:3, :3].T @ (a1z_pose[:3, 3] - base[:3, 3])
            - result[:3, :3] @ tool[:3, 3]
        ) / self.cfg.position_scale
        return result

    def _model_arm_to_so_q(self, model_arm: np.ndarray) -> np.ndarray:
        model_cfg = self.cfg.model
        signs = np.asarray(model_cfg.signs, dtype=np.float64)
        scales = np.asarray(model_cfg.scales, dtype=np.float64)
        offsets = np.asarray(model_cfg.offsets, dtype=np.float64)
        so_q = self._last_so_q.copy()
        so_q[: signs.size] = ((model_arm - offsets) / scales * signs) * DEG2RAD
        return so_q

    def _so_q_to_model_arm(self, so_q: np.ndarray) -> np.ndarray:
        model_cfg = self.cfg.model
        signs = np.asarray(model_cfg.signs, dtype=np.float64)
        scales = np.asarray(model_cfg.scales, dtype=np.float64)
        offsets = np.asarray(model_cfg.offsets, dtype=np.float64)
        return scales * signs * (so_q[: signs.size] * RAD2DEG) + offsets

    def _gripper_to_model(self, value: float) -> float:
        return gripper_to_model(
            value, self.cfg.model.gripper_deg_closed, self.cfg.model.gripper_deg_open
        )

    def _model_to_gripper(self, value: float) -> float:
        return model_to_gripper(
            value, self.cfg.model.gripper_deg_closed, self.cfg.model.gripper_deg_open
        )

    def state_to_model(self, joints_rad: np.ndarray, gripper_norm: float) -> np.ndarray:
        joints = np.asarray(joints_rad, dtype=np.float64)
        if joints.shape != (self._a1z.nq,) or not np.all(np.isfinite(joints)):
            raise ValueError("invalid A1Z state for kinematic retargeting")
        so_target = self._a1z_to_so_pose(self._a1z.fk(joints))
        converged, so_q = self._so100.ik(so_target, self._last_so_q)
        if not converged:
            raise ValueError("SO100 IK did not converge for the observed A1Z pose")
        self._last_so_q = so_q
        return np.concatenate(
            [self._so_q_to_model_arm(so_q), [self._gripper_to_model(gripper_norm)]]
        ).astype(np.float32)

    def model_to_state(
        self, action_model: np.ndarray, prev_joints_rad: np.ndarray
    ) -> tuple[np.ndarray, float]:
        action = np.asarray(action_model, dtype=np.float64)
        arm_count = len(self.cfg.model.signs)
        if action.shape != (arm_count + 1,) or not np.all(np.isfinite(action)):
            raise ValueError(f"expected {arm_count + 1} finite model action values")
        so_q = self._model_arm_to_so_q(action[:arm_count])
        target = self._so_to_a1z_pose(self._so100.fk(so_q))
        converged, a1z_q = self._a1z.ik(target, np.asarray(prev_joints_rad, dtype=np.float64))
        if not converged:
            raise ValueError("A1Z IK did not converge for the SO100 action")
        self._last_so_q = so_q
        return a1z_q.astype(np.float32), self._model_to_gripper(float(action[-1]))
