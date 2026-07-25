"""Two-view camera observations and fail-closed frame freshness checks."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

MAX_JPEG_BYTES = 5 * 1024 * 1024
MIN_JPEG_BYTES = 128


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CameraView(str, Enum):
    EXTERIOR_RIGHT = "exterior_right"
    WRIST = "wrist"


REQUIRED_MANIPULATION_VIEWS = (
    CameraView.EXTERIOR_RIGHT,
    CameraView.WRIST,
)


@dataclass(frozen=True)
class VisionFrame:
    view: CameraView
    jpeg: bytes
    captured_at: datetime
    received_at: datetime
    source: str
    orientation_degrees: int = 0

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.jpeg).hexdigest()

    def age_seconds(self, *, now: datetime | None = None) -> float:
        reference = now or utc_now()
        return max(0.0, (reference - self.captured_at).total_seconds())

    def summary(self, *, now: datetime | None = None) -> dict[str, object]:
        return {
            "view": self.view.value,
            "captured_at": self.captured_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "age_seconds": round(self.age_seconds(now=now), 3),
            "source": self.source,
            "orientation_degrees": self.orientation_degrees,
            "bytes": len(self.jpeg),
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class ObservationSet:
    captured_at: datetime
    frames: dict[CameraView, VisionFrame]

    def summaries(self, *, now: datetime | None = None) -> list[dict[str, object]]:
        return [
            self.frames[view].summary(now=now)
            for view in REQUIRED_MANIPULATION_VIEWS
            if view in self.frames
        ]


class MissingCameraEvidence(RuntimeError):
    """Raised when a manipulation decision lacks either fresh required view."""


def parse_captured_at(value: str | None, *, now: datetime | None = None) -> datetime:
    if not value:
        return now or utc_now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_jpeg(jpeg: bytes) -> None:
    if not MIN_JPEG_BYTES <= len(jpeg) <= MAX_JPEG_BYTES:
        raise ValueError(f"JPEG size must be between {MIN_JPEG_BYTES} and {MAX_JPEG_BYTES} bytes")
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("Camera frame must be a complete JPEG image")


class FrameStore:
    """Thread-safe latest-frame store with atomic two-view snapshots."""

    def __init__(self) -> None:
        self._frames: dict[CameraView, VisionFrame] = {}
        self._lock = threading.Lock()

    def put(
        self,
        view: CameraView | str,
        jpeg: bytes,
        *,
        captured_at: datetime | None = None,
        source: str = "unknown",
        orientation_degrees: int = 0,
        received_at: datetime | None = None,
    ) -> VisionFrame:
        selected_view = CameraView(view)
        # Some UVC MJPEG drivers pad a valid JPEG frame with NUL bytes.
        jpeg = jpeg.rstrip(b"\x00")
        validate_jpeg(jpeg)
        if orientation_degrees not in {0, 90, 180, 270}:
            raise ValueError("orientation_degrees must be one of 0, 90, 180, 270")
        captured = captured_at or utc_now()
        received = received_at or utc_now()
        if captured.tzinfo is None or received.tzinfo is None:
            raise ValueError("camera timestamps must include a timezone")
        if captured > received:
            skew = (captured - received).total_seconds()
            if skew > 5:
                raise ValueError("captured_at is more than 5 seconds in the future")
        frame = VisionFrame(
            view=selected_view,
            jpeg=bytes(jpeg),
            captured_at=captured.astimezone(timezone.utc),
            received_at=received.astimezone(timezone.utc),
            source=source.strip()[:128] or "unknown",
            orientation_degrees=orientation_degrees,
        )
        with self._lock:
            self._frames[selected_view] = frame
        return frame

    def snapshot(
        self,
        *,
        required_views: Iterable[CameraView] = REQUIRED_MANIPULATION_VIEWS,
        max_age_seconds: float = 3.0,
        now: datetime | None = None,
    ) -> ObservationSet:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be greater than zero")
        observed_at = now or utc_now()
        requested = tuple(required_views)
        with self._lock:
            frames = {view: self._frames.get(view) for view in requested}
        missing = [view.value for view, frame in frames.items() if frame is None]
        stale = [
            view.value
            for view, frame in frames.items()
            if frame is not None and frame.age_seconds(now=observed_at) > max_age_seconds
        ]
        if missing or stale:
            details: list[str] = []
            if missing:
                details.append(f"missing={','.join(missing)}")
            if stale:
                details.append(f"stale={','.join(stale)}")
            raise MissingCameraEvidence(
                "Two-view observation is incomplete: " + " ".join(details)
            )
        return ObservationSet(
            captured_at=observed_at,
            frames={view: frame for view, frame in frames.items() if frame is not None},
        )

    def latest(
        self,
        view: CameraView | str,
        *,
        max_age_seconds: float = 3.0,
        now: datetime | None = None,
    ) -> VisionFrame:
        selected = CameraView(view)
        return self.snapshot(
            required_views=(selected,),
            max_age_seconds=max_age_seconds,
            now=now,
        ).frames[selected]

    def status(
        self,
        *,
        max_age_seconds: float = 3.0,
        now: datetime | None = None,
    ) -> dict[str, object]:
        observed_at = now or utc_now()
        with self._lock:
            frames = dict(self._frames)
        views: dict[str, object] = {}
        for view in REQUIRED_MANIPULATION_VIEWS:
            frame = frames.get(view)
            summary = frame.summary(now=observed_at) if frame else None
            views[view.value] = {
                "present": frame is not None,
                "fresh": bool(
                    frame is not None and frame.age_seconds(now=observed_at) <= max_age_seconds
                ),
                "frame": summary,
            }
        ready = all(bool(item["fresh"]) for item in views.values())
        return {
            "ready": ready,
            "required_views": [view.value for view in REQUIRED_MANIPULATION_VIEWS],
            "max_age_seconds": max_age_seconds,
            "checked_at": observed_at.isoformat(),
            "views": views,
        }
