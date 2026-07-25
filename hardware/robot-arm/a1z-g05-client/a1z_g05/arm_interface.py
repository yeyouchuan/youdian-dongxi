"""A1Z arm interface: one abstraction, two backends.

``ArmInterface`` mirrors the subset of the dimos ``ManipulatorAdapter`` protocol
that this harness needs (SI units: joints in radians, gripper normalized 0..1),
so swapping the mock for the real A1Z later is a drop-in.

Backends
--------
MockA1ZArm
    Fully in-memory, runs on macOS. Prefers the dimos ``MockAdapter`` (imported
    lazily) and falls back to a tiny built-in mock if dimos is not importable,
    so the end-to-end pipeline always runs on the laptop.

DimosA1ZArm
    Placeholder for the real A1Z driven through the dimos ControlCoordinator.
    On the A1Z, joint state is published on ``coordinator_joint_state``
    (Out[JointState]), joint commands go to ``joint_command`` (In[JointState]),
    and the gripper is driven via the coordinator RPC ``set_gripper_position``.
    A real dimos hardware adapter (Piper-style CAN/serial) is required first;
    those drivers are Linux-only, so this backend is a stub until the arm is
    wired up. See config.py -> make_a1z_hardware(adapter_type=..., address=...).
"""

from __future__ import annotations

import logging
import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ArmState:
    """A1Z proprioceptive state in SI units."""

    joints_rad: np.ndarray  # shape (dof,)
    gripper: float          # official SDK: normalized 0.0 (closed) .. 1.0 (open)


class ArmInterface(Protocol):
    """Minimal duck-typed arm interface (subset of dimos ManipulatorAdapter)."""

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def read_state(self) -> ArmState: ...
    def write_state(self, joints_rad: np.ndarray, gripper_norm: float) -> None: ...
    def write_joint_positions(self, joints_rad: np.ndarray) -> None: ...
    def write_gripper(self, gripper_norm: float) -> None: ...
    def home(self) -> None: ...
    def estop(self) -> None: ...
    def release_estop(self) -> None: ...
    @property
    def dof(self) -> int: ...


# --------------------------------------------------------------------------- #
# Mock backend (macOS)                                                        #
# --------------------------------------------------------------------------- #

class MockA1ZArm:
    """In-memory A1Z that mirrors the dimos A1Z config (6 DOF + gripper).

    A background worker rate-limits motion toward the commanded target so the
    live GUI shows realistic gradual movement rather than teleporting.
    """

    def __init__(
        self,
        dof: int = 6,
        home_joints_rad: list[float] | None = None,
        home_gripper: float = 0.0,
        max_inner_delta_rad: float = 0.05,
        worker_hz: float = 100.0,
    ) -> None:
        self._dof = int(dof)
        self._home = np.asarray(home_joints_rad or [0.0] * dof, dtype=np.float32)
        self._home_gripper = float(home_gripper)
        self._max_inner_delta = float(max_inner_delta_rad)
        self._worker_dt = 1.0 / float(worker_hz)

        self._adapter = self._make_adapter()
        self._target = self._home.copy()
        self._gripper_target = self._home_gripper
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _make_adapter(self):
        """Prefer the real dimos MockAdapter; fall back to a tiny local mock."""
        try:
            from dimos.hardware.manipulators.mock.adapter import MockAdapter

            adapter = MockAdapter(dof=self._dof, initial_positions=self._home.tolist())
            logger.info("[MockA1ZArm] using dimos MockAdapter")
            return adapter
        except Exception as exc:  # dimos not importable on this machine
            logger.warning("[MockA1ZArm] dimos MockAdapter unavailable (%s); using local mock", exc)
            return _LocalMock(self._dof, self._home.tolist())

    @property
    def dof(self) -> int:
        return self._dof

    def connect(self) -> None:
        self._adapter.connect()
        self._adapter.write_enable(True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="MockA1ZArm")
        self._thread.start()
        logger.info("[MockA1ZArm] connected")

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            self._adapter.disconnect()
        except Exception:
            pass
        logger.info("[MockA1ZArm] disconnected")

    def read_state(self) -> ArmState:
        joints = np.asarray(self._adapter.read_joint_positions(), dtype=np.float32)
        gripper = self._adapter.read_gripper_position()
        return ArmState(joints_rad=joints, gripper=float(gripper if gripper is not None else 0.0))

    def write_joint_positions(self, joints_rad: np.ndarray) -> None:
        with self._lock:
            self._target = np.asarray(joints_rad, dtype=np.float32).copy()

    def write_state(self, joints_rad: np.ndarray, gripper_norm: float) -> None:
        self.write_joint_positions(joints_rad)
        self.write_gripper(gripper_norm)

    def write_gripper(self, gripper_norm: float) -> None:
        with self._lock:
            self._gripper_target = float(np.clip(gripper_norm, 0.0, 1.0))

    def home(self) -> None:
        self.write_joint_positions(self._home)
        self.write_gripper(self._home_gripper)
        # Block briefly so the worker converges before inference starts.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if np.max(np.abs(self.read_state().joints_rad - self._home)) < 0.01:
                break
            time.sleep(self._worker_dt)

    def estop(self) -> None:
        with self._lock:
            self._target = np.asarray(self._adapter.read_joint_positions(), dtype=np.float32)

    def release_estop(self) -> None:
        return

    def _worker(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                target = self._target.copy()
                grip = self._gripper_target
            cur = np.asarray(self._adapter.read_joint_positions(), dtype=np.float32)
            delta = np.clip(target - cur, -self._max_inner_delta, self._max_inner_delta)
            self._adapter.write_joint_positions((cur + delta).tolist())
            self._adapter.write_gripper_position(grip)
            time.sleep(self._worker_dt)


class _LocalMock:
    """Fallback in-memory adapter used only if dimos cannot be imported."""

    def __init__(self, dof: int, initial: list[float]) -> None:
        self._dof = dof
        self._pos = list(initial)
        self._grip = 0.0
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def write_enable(self, enable: bool) -> bool:
        return True

    def read_joint_positions(self) -> list[float]:
        return list(self._pos)

    def write_joint_positions(self, positions: list[float], velocity: float = 1.0) -> bool:
        if len(positions) != self._dof:
            return False
        self._pos = list(positions)
        return True

    def read_gripper_position(self) -> float:
        return self._grip

    def write_gripper_position(self, position: float) -> bool:
        self._grip = float(position)
        return True


# --------------------------------------------------------------------------- #
# Real A1Z backend (stub — Linux/CAN, later stage)                            #
# --------------------------------------------------------------------------- #

class DimosA1ZArm:
    """Real A1Z through the dimos ControlCoordinator. STUB — not yet wired.

    Intended implementation once the arm is connected:
      1. Build/launch the A1Z coordinator blueprint
         (dimos.robot.manipulators.a1z.blueprints.basic.coordinator_a1z) with a
         REAL adapter: make_a1z_hardware("arm", adapter_type="<a1z>", address=...).
         A dedicated A1Z ManipulatorAdapter must be implemented first, modeled on
         dimos/hardware/manipulators/piper/adapter.py (CAN bus).
      2. read_state():  get_joint_positions() + get_gripper_position("arm").
      3. write_joint_positions(): publish a JointState on ``joint_command``.
      4. write_gripper(): coordinator RPC set_gripper_position("arm", pos).
    Note: dimos CAN/serial adapters are Linux-only, so this backend will not run
    on macOS. Validate the full pipeline with MockA1ZArm on the mac first.
    """

    def __init__(self, dof: int = 6, address: str | None = None) -> None:
        self._dof = dof
        self._address = address

    @property
    def dof(self) -> int:
        return self._dof

    def connect(self) -> None:
        raise NotImplementedError(
            "DimosA1ZArm is a stub. Implement a real A1Z adapter (Piper-style) and "
            "launch the coordinator_a1z blueprint on a Linux host connected to the arm. "
            "Use backend='mock' on macOS for now."
        )

    def disconnect(self) -> None: ...
    def read_state(self) -> ArmState:  # pragma: no cover - stub
        raise NotImplementedError
    def write_joint_positions(self, joints_rad: np.ndarray) -> None:  # pragma: no cover
        raise NotImplementedError
    def write_state(self, joints_rad: np.ndarray, gripper_norm: float) -> None:  # pragma: no cover
        raise NotImplementedError
    def write_gripper(self, gripper_norm: float) -> None:  # pragma: no cover
        raise NotImplementedError
    def home(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError
    def estop(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError
    def release_estop(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError


class A1ZCtlArm:
    """Read real A1Z telemetry through the official SDK's local Unix socket.

    This backend is intentionally observation-only. The official ``move`` RPC
    is blocking and unsuitable for a 15 Hz VLA stream, so model writes are
    rejected. E-stop is still forwarded immediately.
    """

    def __init__(
        self,
        dof: int = 6,
        socket_path: str = "/tmp/a1z.sock",
        allow_stream_writes: bool = False,
        max_stream_jump_deg: float = 3.0,
    ) -> None:
        self._dof = int(dof)
        self._socket_path = socket_path
        self._allow_stream_writes = bool(allow_stream_writes)
        self._max_stream_jump_deg = float(max_stream_jump_deg)

    @property
    def dof(self) -> int:
        return self._dof

    def _request(self, command: str, args: dict | None = None) -> dict:
        payload = (json.dumps({"cmd": command, "args": args or {}}) + "\n").encode()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(self._socket_path)
            sock.sendall(payload)
            chunks = bytearray()
            while b"\n" not in chunks:
                part = sock.recv(4096)
                if not part:
                    break
                chunks.extend(part)
        response = json.loads(bytes(chunks).split(b"\n", 1)[0])
        if not response.get("ok"):
            raise RuntimeError(response.get("error", f"A1Z RPC {command!r} failed"))
        return response.get("data", {})

    def connect(self) -> None:
        self._validate_daemon_health(self._request("status"))

    def disconnect(self) -> None:
        # Never stop the official daemon here: stopping disables torque and the
        # brake-less A1Z can fall.
        return

    def read_state(self) -> ArmState:
        data = self._request("status")
        self._validate_daemon_health(data)
        joints = np.deg2rad(np.asarray(data["pos_deg"], dtype=np.float32))
        if "gripper" not in data or data["gripper"] is None:
            raise RuntimeError("A1Z daemon did not provide required gripper telemetry")
        gripper = float(data["gripper"])
        if not np.isfinite(gripper) or not 0.0 <= gripper <= 1.0:
            raise RuntimeError(f"invalid A1Z gripper telemetry: {gripper!r}")
        return ArmState(joints_rad=joints, gripper=gripper)

    @staticmethod
    def _validate_daemon_health(data: dict) -> None:
        if data.get("control_thread_alive") is not True or data.get("estopped") is not False:
            raise RuntimeError(
                "A1Z daemon control thread is not healthy; stop all safe_server "
                "processes and start exactly one"
            )

    def write_joint_positions(self, joints_rad: np.ndarray) -> None:
        raise RuntimeError("use atomic write_state for A1Z streaming")

    def write_state(self, joints_rad: np.ndarray, gripper_norm: float) -> None:
        if not self._allow_stream_writes:
            raise RuntimeError("a1zctl stream writes are disabled by configuration")
        joints = np.asarray(joints_rad, dtype=np.float64)
        if joints.shape != (self._dof,) or not np.all(np.isfinite(joints)):
            raise ValueError("A1Z stream target must contain six finite joints")
        gripper = float(gripper_norm)
        if not np.isfinite(gripper) or not 0.0 <= gripper <= 1.0:
            raise ValueError("A1Z stream gripper must be finite and in [0, 1]")
        self._request(
            "stream",
            {
                "joints_deg": np.rad2deg(joints).tolist(),
                "gripper": gripper,
                "max_jump_deg": self._max_stream_jump_deg,
            },
        )

    def write_gripper(self, gripper_norm: float) -> None:
        raise RuntimeError("a1zctl backend is shadow-only; streaming model writes are disabled")

    def home(self) -> None:
        raise RuntimeError("a1zctl backend never homes automatically")

    def estop(self) -> None:
        self._request("estop")

    def release_estop(self) -> None:
        self._request("release")


def make_arm(cfg: dict) -> ArmInterface:
    """Factory: build the arm backend selected in config.yaml -> arm.backend."""
    backend = cfg.get("backend", "mock")
    if backend == "mock":
        return MockA1ZArm(
            dof=int(cfg.get("dof", 6)),
            home_joints_rad=cfg.get("home_joints_rad"),
            home_gripper=float(cfg.get("home_gripper", 0.0)),
        )
    if backend == "dimos":
        return DimosA1ZArm(dof=int(cfg.get("dof", 6)), address=cfg.get("address"))
    if backend == "a1zctl":
        return A1ZCtlArm(
            dof=int(cfg.get("dof", 6)),
            socket_path=str(cfg.get("socket_path", "/tmp/a1z.sock")),
            allow_stream_writes=bool(cfg.get("allow_stream_writes", False)),
            max_stream_jump_deg=float(cfg.get("max_stream_jump_deg", 3.0)),
        )
    raise ValueError(
        f"unknown arm backend: {backend!r} (expected 'mock', 'a1zctl', or 'dimos')"
    )
