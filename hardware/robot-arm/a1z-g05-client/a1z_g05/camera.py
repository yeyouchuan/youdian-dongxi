"""Wrist-camera capture worker (OpenCV, cross-platform: Windows + macOS).

Reads frames in a background thread so control/inference never block on the
camera. Provides frames in two forms:
  - BGR HWC uint8 for on-screen display (Gradio expects RGB, converted there)
  - RGB CHW uint8 for the G0.5 server (matches experiments/so100 client)

On Windows the default MSMF backend can be slow/unreliable to open a webcam;
DirectShow ("dshow") is usually faster and more compatible. Select it via
config.yaml -> camera.backend.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Named OpenCV capture backends. "auto" lets OpenCV choose (cv2.CAP_ANY).
_BACKENDS = {
    "auto": cv2.CAP_ANY,
    "dshow": getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY),   # Windows DirectShow
    "msmf": getattr(cv2, "CAP_MSMF", cv2.CAP_ANY),     # Windows Media Foundation
    "avfoundation": getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY),  # macOS
    "v4l2": getattr(cv2, "CAP_V4L2", cv2.CAP_ANY),     # Linux
}


def orient_frame(frame: np.ndarray, *, rotate_180: bool) -> np.ndarray:
    """Apply the configured fixed camera mounting orientation."""
    if not rotate_180:
        return frame
    return np.ascontiguousarray(frame[::-1, ::-1])


def load_rgb_chw_file(
    path: str | Path,
    *,
    target_shape: tuple[int, int, int],
    max_age_s: float,
    rotate_180: bool = False,
    now: float | None = None,
) -> np.ndarray:
    """Load one fresh JPEG/PNG file as the RGB CHW tensor expected by G0.5."""
    if len(target_shape) != 3 or target_shape[0] != 3 or any(x <= 0 for x in target_shape):
        raise ValueError("file image target_shape must be positive CHW with three channels")
    if not np.isfinite(max_age_s) or max_age_s <= 0:
        raise ValueError("file image max_age_s must be finite and positive")
    selected = Path(path)
    try:
        modified = selected.stat().st_mtime
    except FileNotFoundError as exc:
        raise RuntimeError(f"image file is missing: {selected}") from exc
    age = max(0.0, (time.time() if now is None else now) - modified)
    if age > max_age_s:
        raise RuntimeError(f"image file is stale ({age:.2f}s): {selected}")
    frame = cv2.imread(str(selected), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(f"image file cannot be decoded: {selected}")
    frame = orient_frame(frame, rotate_180=rotate_180)
    _, target_height, target_width = target_shape
    if frame.shape[:2] != (target_height, target_width):
        frame = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.uint8)


class CameraWorker:
    """Background-thread OpenCV camera capture for the A1Z wrist camera."""

    def __init__(
        self,
        index: int | str = 0,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        backend: str = "auto",
        fourcc: str | None = None,
        rotate_180: bool = False,
    ) -> None:
        self.index = index
        self._rotate_180 = bool(rotate_180)
        backend_flag = _BACKENDS.get(str(backend).lower(), cv2.CAP_ANY)
        self._cap = cv2.VideoCapture(index, backend_flag)
        if fourcc:
            if len(fourcc) != 4:
                raise ValueError("camera fourcc must contain exactly four characters")
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_time: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"Camera-{index}")
        self._thread.start()
        if not self._cap.isOpened():
            logger.warning("[Camera-%s] could not open device (backend=%s); frames will be None",
                           index, backend)
        else:
            logger.info(
                "[Camera-%s] started (%dx%d @ %dfps, backend=%s, fourcc=%s)",
                index, width, height, fps, backend, fourcc or "auto",
            )

    def _loop(self) -> None:
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if ok and frame is not None:
                frame = orient_frame(frame, rotate_180=self._rotate_180)
                with self._lock:
                    self._frame = frame  # BGR HWC uint8
                    self._frame_time = time.monotonic()

    def read_bgr(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def read_rgb(self) -> np.ndarray | None:
        """RGB HWC uint8 (for Gradio display)."""
        frame = self.read_bgr()
        return None if frame is None else cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def read_rgb_chw(self) -> np.ndarray | None:
        """RGB CHW uint8 (format the G0.5 server expects)."""
        rgb = self.read_rgb()
        return None if rgb is None else np.ascontiguousarray(rgb.transpose(2, 0, 1))

    def frame_age_s(self) -> float | None:
        """Age of the newest captured frame, or ``None`` before the first frame."""
        with self._lock:
            captured = self._frame_time
        return None if captured is None else time.monotonic() - captured

    def release(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._cap.release()
        logger.info("[Camera-%s] released", self.index)
