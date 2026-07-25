"""Inference controller: the tick loop that makes the A1Z do what you say.

Each tick (at ``action_fps`` Hz):
  1. Read A1Z proprio state (joints + gripper).
  2. If the server needs a fresh observation (need_obs / task changed):
        - grab a wrist-camera frame (+ zero-padded extra image keys)
        - convert proprio to the so100 model frame
        - send the full observation to the G0.5 server
     otherwise send ``{}`` and let the server return the next cached chunk step.
  3. Convert the returned model-frame action back to A1Z joints/gripper.
  4. Velocity-limit the joint step and command the arm.

Runs in a background thread so the Gradio UI stays responsive. All shared,
UI-visible fields are guarded by locks.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from a1z_g05.arm_interface import ArmInterface
from a1z_g05.camera import CameraWorker, load_rgb_chw_file
from a1z_g05.g05_client import G05PolicyClient, build_obs
from a1z_g05.mapping import (
    A1Z_SOFT_LIMITS_RAD,
    A1ZSo100Mapping,
    clip_step,
    project_target_to_joint_limits,
    validate_joint_step,
    validate_joint_limits,
)

logger = logging.getLogger(__name__)


@dataclass
class ControllerStatus:
    """Snapshot of the live loop state for the GUI."""

    running: bool = False
    connected: bool = False
    estopped: bool = False
    task: str = ""
    step: int = 0
    need_obs: bool = True
    cot_text: str = ""
    last_error: str = ""
    joints_rad: list[float] = field(default_factory=list)
    gripper: float = 0.0
    action_hz: float = 0.0
    shadow_mode: bool = True


class InferenceController:
    """Owns the arm, camera and G0.5 client; drives the closed loop."""

    def __init__(
        self,
        *,
        arm: ArmInterface,
        camera: CameraWorker,
        mapping: A1ZSo100Mapping,
        server: dict[str, Any],
        control: dict[str, Any],
        camera_cfg: dict[str, Any],
    ) -> None:
        self._arm = arm
        self._camera = camera
        self._mapping = mapping
        self._server = server
        self._control = control
        self._camera_cfg = camera_cfg

        self._client: G05PolicyClient | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self._action_fps = float(control.get("action_fps", 15.0))
        self._max_step_deg = float(control.get("max_step_deg", 8.0))
        self._max_target_limit_overshoot_deg = float(
            control.get("max_target_limit_overshoot_deg", 0.0)
        )
        self._embodiment = str(control.get("embodiment_type", "so100"))
        self._execute_actions = bool(control.get("execute_actions", False))
        max_steps = control.get("max_steps")
        self._max_steps = None if max_steps is None else int(max_steps)
        self._require_camera = bool(control.get("require_camera", True))
        self._max_camera_age_s = float(control.get("max_camera_age_s", 0.5))
        self._joint_limits = np.asarray(
            control.get("joint_limits_rad", A1Z_SOFT_LIMITS_RAD), dtype=np.float32
        )
        self._locked_joint_indices = tuple(
            sorted(set(int(i) for i in control.get("locked_joint_indices", [])))
        )
        self._locked_joint_targets: np.ndarray | None = None
        if any(i < 0 or i >= self._joint_limits.shape[0] for i in self._locked_joint_indices):
            raise ValueError("locked_joint_indices contains an invalid joint")
        if not np.isfinite(self._action_fps) or self._action_fps <= 0:
            raise ValueError("action_fps must be finite and positive")
        if not np.isfinite(self._max_step_deg) or self._max_step_deg <= 0:
            raise ValueError("max_step_deg must be finite and positive")
        if (
            not np.isfinite(self._max_target_limit_overshoot_deg)
            or self._max_target_limit_overshoot_deg < 0
            or self._max_target_limit_overshoot_deg > 5
        ):
            raise ValueError(
                "max_target_limit_overshoot_deg must be finite and in [0, 5]"
            )
        if not np.isfinite(self._max_camera_age_s) or self._max_camera_age_s <= 0:
            raise ValueError("max_camera_age_s must be finite and positive")
        if self._max_steps is not None and self._max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if (
            self._joint_limits.shape != A1Z_SOFT_LIMITS_RAD.shape
            or not np.all(np.isfinite(self._joint_limits))
            or np.any(self._joint_limits[:, 0] > self._joint_limits[:, 1])
            or np.any(self._joint_limits[:, 0] < A1Z_SOFT_LIMITS_RAD[:, 0])
            or np.any(self._joint_limits[:, 1] > A1Z_SOFT_LIMITS_RAD[:, 1])
        ):
            raise ValueError("joint_limits_rad must be finite and no wider than official limits")

        self._cam_key = str(camera_cfg.get("server_key", "wrist_right"))
        self._zero_pad_keys = list(camera_cfg.get("zero_pad_keys", []))
        self._dummy_shape = tuple(int(x) for x in camera_cfg.get("dummy_shape", (3, 480, 640)))
        raw_file_images = camera_cfg.get("file_images", {})
        if not isinstance(raw_file_images, dict):
            raise ValueError("camera.file_images must be a mapping")
        self._file_images: dict[str, dict[str, Any]] = {}
        for key, value in raw_file_images.items():
            if not isinstance(value, dict) or not value.get("path"):
                raise ValueError(f"camera.file_images.{key} must include a path")
            if key == self._cam_key:
                raise ValueError(f"camera.file_images duplicates primary camera key {key}")
            self._file_images[str(key)] = {
                "path": str(value["path"]),
                "rotate_180": bool(value.get("rotate_180", False)),
                "max_age_s": float(value.get("max_age_s", 3.0)),
            }

        self._lock = threading.Lock()
        self._status = ControllerStatus(shadow_mode=not self._execute_actions)
        self._task = ""
        self._task_changed = False
        self._estop = False
        self._need_obs = True

    # -- status -------------------------------------------------------------

    def status(self) -> ControllerStatus:
        with self._lock:
            st = ControllerStatus(**vars(self._status))
        return st

    def set_task(self, task: str) -> None:
        task = (task or "").strip()
        if not task:
            return
        with self._lock:
            self._task = task
            self._task_changed = True
        logger.info("[Controller] task set: %r", task)

    def set_estop(self, engaged: bool) -> None:
        if engaged:
            # Latch locally first so an RPC failure cannot permit inference.
            with self._lock:
                self._estop = True
            self._arm.estop()
        else:
            # Keep the local latch until the daemon acknowledges the release.
            self._arm.release_estop()
            with self._lock:
                self._estop = False
        logger.warning("[Controller] E-STOP %s", "ENGAGED" if engaged else "released")

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            self._arm.connect()
            if self._control.get("home_on_start", False):
                self._arm.home()
            self._client = G05PolicyClient(
                host=self._server.get("host", "localhost"),
                port=self._server.get("port", 8765),
                timeout_s=float(self._server.get("timeout_s", 30.0)),
            )
            self._client.connect()
        except Exception:
            if self._client is not None:
                self._client.close()
                self._client = None
            self._arm.disconnect()
            raise
        self._stop.clear()
        self._need_obs = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="InferenceController")
        self._thread.start()
        with self._lock:
            self._status.running = True
            self._status.connected = True
            self._status.last_error = ""

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._client is not None:
            self._client.close()
            self._client = None
        try:
            self._arm.disconnect()
        except Exception:
            pass
        with self._lock:
            self._status.running = False
            self._status.connected = False

    # -- main loop ----------------------------------------------------------

    def _loop(self) -> None:
        assert self._client is not None
        period = 1.0 / self._action_fps
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self._one_tick()
            except Exception as exc:  # keep the loop alive; surface to GUI
                logger.error("[Controller] tick error: %s", exc, exc_info=True)
                with self._lock:
                    self._status.last_error = str(exc)
                self._need_obs = True
                time.sleep(0.5)
                continue
            elapsed = time.monotonic() - t0
            with self._lock:
                self._status.action_hz = 1.0 / elapsed if elapsed > 0 else 0.0
            time.sleep(max(0.0, period - elapsed))

    def _one_tick(self) -> None:
        assert self._client is not None

        with self._lock:
            estopped = self._estop
            task = self._task
            task_changed = self._task_changed
            step = self._status.step
            self._task_changed = False

        state = self._arm.read_state()
        if self._locked_joint_indices and self._locked_joint_targets is None:
            # A locked joint must remain anchored to the position measured at
            # controller startup. Reusing each tick's measured value would
            # silently ratchet gravity/backdrive drift into the next command.
            self._locked_joint_targets = np.asarray(
                state.joints_rad, dtype=np.float32
            ).copy()

        # E-stop: hold current pose, keep telemetry fresh, do not command motion.
        if estopped or not task or (
            self._max_steps is not None and step >= self._max_steps
        ):
            with self._lock:
                self._status.estopped = estopped
                self._status.task = task
                self._status.joints_rad = state.joints_rad.tolist()
                self._status.gripper = state.gripper
                self._status.need_obs = True
            self._need_obs = True
            return

        if task_changed:
            self._need_obs = True

        # If measured feedback is already outside a soft limit, recover under
        # deterministic local control before asking the policy for any action.
        # This prevents an out-of-distribution observation from deciding which
        # way an already unsafe joint should move.
        checked = np.ones(state.joints_rad.size, dtype=bool)
        checked[list(self._locked_joint_indices)] = False
        outside = checked & (
            (state.joints_rad < self._joint_limits[:, 0])
            | (state.joints_rad > self._joint_limits[:, 1])
        )
        if self._execute_actions and np.any(outside):
            recovery_target = np.asarray(state.joints_rad, dtype=np.float32).copy()
            recovery_target[checked] = np.clip(
                recovery_target[checked],
                self._joint_limits[checked, 0],
                self._joint_limits[checked, 1],
            )
            safe_joints = clip_step(
                recovery_target, state.joints_rad, self._max_step_deg
            )
            validate_joint_step(
                safe_joints,
                state.joints_rad,
                self._joint_limits,
                self._locked_joint_indices,
            )
            self._arm.write_state(safe_joints, state.gripper)
            self._need_obs = True
            names = ", ".join(f"J{i + 1}" for i in np.flatnonzero(outside))
            logger.warning(
                "[Controller] recovering measured joints to soft limits before inference: %s",
                names,
            )
            with self._lock:
                self._status.estopped = False
                self._status.task = task
                self._status.need_obs = True
                self._status.joints_rad = safe_joints.tolist()
                self._status.gripper = state.gripper
                self._status.last_error = ""
            return

        if self._need_obs:
            images = self._collect_images()
            state_model = self._mapping.state_to_model(state.joints_rad, state.gripper)
            raw_obs = build_obs(
                images=images,
                state_model_deg=state_model,
                task=task,
                embodiment_type=self._embodiment,
                frequency=self._action_fps,
            )
        else:
            raw_obs = {}

        response = self._client.infer(raw_obs)

        self._need_obs = bool(response.get("need_obs", True))
        cot = response.get("cot_text") or ""

        action = response.get("action", {})
        action_model = np.asarray(action.get("right_arm"), dtype=np.float32)
        target_joints, gripper_norm = self._mapping.model_to_state(action_model, state.joints_rad)
        if self._locked_joint_targets is not None:
            target_joints = np.asarray(target_joints, dtype=np.float32).copy()
            target_joints[list(self._locked_joint_indices)] = (
                self._locked_joint_targets[list(self._locked_joint_indices)]
            )
        raw_target_joints = target_joints
        target_joints = project_target_to_joint_limits(
            target_joints,
            self._joint_limits,
            self._max_target_limit_overshoot_deg,
            self._locked_joint_indices,
        )
        if not np.array_equal(target_joints, raw_target_joints):
            logger.warning(
                "[Controller] projected small model target overshoot to soft limit"
            )
        validate_joint_limits(
            target_joints, self._joint_limits, self._locked_joint_indices
        )
        safe_joints = clip_step(target_joints, state.joints_rad, self._max_step_deg)
        validate_joint_step(
            safe_joints,
            state.joints_rad,
            self._joint_limits,
            self._locked_joint_indices,
        )

        if self._execute_actions:
            self._arm.write_state(safe_joints, gripper_norm)

        with self._lock:
            self._status.estopped = False
            self._status.task = task
            self._status.step += 1
            self._status.need_obs = self._need_obs
            self._status.cot_text = cot
            shown_joints = safe_joints if self._execute_actions else state.joints_rad
            shown_gripper = gripper_norm if self._execute_actions else state.gripper
            self._status.joints_rad = shown_joints.tolist()
            self._status.gripper = shown_gripper
            self._status.last_error = ""

    def _collect_images(self) -> dict[str, np.ndarray]:
        """Collect the live wrist frame, fresh file-backed views, then zero pads."""
        images: dict[str, np.ndarray] = {}
        chw = self._camera.read_rgb_chw()
        age = self._camera.frame_age_s()
        if chw is not None and age is not None and age <= self._max_camera_age_s:
            images[self._cam_key] = chw
        else:
            if self._require_camera:
                detail = "no frame received" if age is None else f"newest frame is {age:.2f}s old"
                raise RuntimeError(f"wrist camera unavailable: {detail}")
            images[self._cam_key] = np.zeros(self._dummy_shape, dtype=np.uint8)
        for key, config in self._file_images.items():
            try:
                images[key] = load_rgb_chw_file(
                    config["path"],
                    target_shape=self._dummy_shape,
                    max_age_s=config["max_age_s"],
                    rotate_180=config["rotate_180"],
                )
            except RuntimeError as exc:
                if self._require_camera:
                    raise RuntimeError(f"{key} camera unavailable: {exc}") from exc
                images[key] = np.zeros(self._dummy_shape, dtype=np.uint8)
        for key in self._zero_pad_keys:
            if key not in images:
                images[key] = np.zeros(self._dummy_shape, dtype=np.uint8)
        return images
