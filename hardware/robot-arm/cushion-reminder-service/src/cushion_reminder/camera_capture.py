"""Live two-view observation adapter for the Mark/WSL camera topology."""

from __future__ import annotations

import base64
import subprocess
from collections.abc import Callable

from .execution import LogCallback
from .vision import (
    REQUIRED_MANIPULATION_VIEWS,
    CameraView,
    FrameStore,
    ObservationSet,
)


def build_mark_wrist_capture_command() -> str:
    """Attach DaBai when needed, resolve it by VID:PID, and emit one JPEG."""
    return r"""
set -eu
usbipd="/mnt/c/Program Files/usbipd-win/usbipd.exe"
test -x "$usbipd"
busid=$("$usbipd" list 2>/dev/null | tr -d '\r' | awk '$2 == "2bc5:0557" {print $1; exit}')
test -n "$busid"
if ! lsusb | grep -q '2bc5:0557'; then
  "$usbipd" attach --wsl --busid "$busid" >/dev/null 2>&1
fi
selected=""
for wait_attempt in 1 2 3 4 5 6 7 8 9 10; do
  for node in /dev/video*; do
    properties=$(udevadm info --query=property --name="$node" 2>/dev/null || true)
    case "$properties" in
      *"ID_VENDOR_ID=2bc5"*"ID_MODEL_ID=0557"*)
        if v4l2-ctl -d "$node" --list-formats-ext 2>/dev/null | grep -q "MJPG"; then
          selected="$node"
          break
        fi
        ;;
    esac
  done
  test -n "$selected" && break
  sleep 1
done
test -n "$selected"
frame=$(mktemp /tmp/a1z-wrist-eval.XXXXXX.jpg)
trap 'rm -f "$frame"' EXIT
captured=0
for attempt in 1 2 3; do
  : >"$frame"
  if timeout 4 v4l2-ctl -d "$selected" \
    --set-fmt-video=width=640,height=480,pixelformat=MJPG \
    --set-parm=5 --stream-mmap=4 --stream-skip=3 --stream-count=1 \
    --stream-to="$frame" --stream-poll >/dev/null 2>&1; then
    captured=1
    break
  fi
  sleep 1
done
test "$captured" = 1
base64 -w0 "$frame"
""".strip()


def build_mark_right_capture_command() -> str:
    """Capture Mark's RGB webcam once, attaching it persistently if needed."""
    return r"""
set -eu
usbipd="/mnt/c/Program Files/usbipd-win/usbipd.exe"
test -x "$usbipd"
busid=$("$usbipd" list 2>/dev/null | tr -d '\r' | awk '$2 == "0408:30c3" {print $1; exit}')
test -n "$busid"
frame=""
cleanup() {
  test -z "$frame" || rm -f "$frame"
}
trap cleanup EXIT
if ! lsusb | grep -q '0408:30c3'; then
  "$usbipd" attach --wsl --busid "$busid" >/dev/null 2>&1
  sleep 3
fi
selected=""
for node in /dev/video*; do
  properties=$(udevadm info --query=property --name="$node" 2>/dev/null || true)
  case "$properties" in
    *"ID_VENDOR_ID=0408"*"ID_MODEL_ID=30c3"*)
      if v4l2-ctl -d "$node" --list-formats-ext 2>/dev/null | grep -q "MJPG"; then
        selected="$node"
        break
      fi
      ;;
  esac
done
test -n "$selected"
mkdir -p /tmp/a1z-vision
frame=$(mktemp /tmp/a1z-right-eval.XXXXXX.jpg)
timeout 12 v4l2-ctl -d "$selected" \
  --set-fmt-video=width=640,height=480,pixelformat=MJPG \
  --set-parm=30 --stream-mmap=4 --stream-skip=2 --stream-count=1 \
  --stream-to="$frame" --stream-poll >/dev/null 2>&1
cp "$frame" /tmp/a1z-vision/exterior-right.next.jpg
mv /tmp/a1z-vision/exterior-right.next.jpg /tmp/a1z-vision/exterior-right.jpg
base64 -w0 "$frame"
""".strip()


class SshMarkObservationAdapter:
    """Captures the fixed Mark exterior and DaBai wrist views at action boundaries."""

    def __init__(
        self,
        *,
        frame_store: FrameStore,
        host: str = "mark",
        max_age_seconds: float = 8.0,
        capture_right: Callable[[], bytes] | None = None,
        capture_wrist: Callable[[], bytes] | None = None,
    ) -> None:
        self._frames = frame_store
        self._host = host
        self._max_age_seconds = max_age_seconds
        self._capture_right_override = capture_right
        self._capture_wrist_override = capture_wrist

    def start(self, log: LogCallback) -> None:
        log(
            "camera",
            "Two-view observer started",
            {
                "views": [
                    CameraView.EXTERIOR_RIGHT.value,
                    CameraView.WRIST.value,
                ]
            },
        )

    def observe(self, *, phase: str, log: LogCallback) -> ObservationSet:
        right_jpeg = (
            self._capture_right_override()
            if self._capture_right_override is not None
            else self._capture_right_over_ssh()
        )
        self._frames.put(
            CameraView.EXTERIOR_RIGHT,
            right_jpeg,
            source="mark-webcam-0408:30c3-boundary",
        )
        wrist_jpeg = (
            self._capture_wrist_override()
            if self._capture_wrist_override is not None
            else self._capture_wrist_over_ssh()
        )
        self._frames.put(
            CameraView.WRIST,
            wrist_jpeg,
            source="mark-dabai-2bc5:0557",
            orientation_degrees=180,
        )
        observation = self._frames.snapshot(
            required_views=REQUIRED_MANIPULATION_VIEWS,
            max_age_seconds=self._max_age_seconds,
        )
        log(
            "camera",
            f"Captured two-view {phase} observation",
            {"phase": phase, "frames": observation.summaries()},
        )
        return observation

    def stop(self, log: LogCallback) -> None:
        log("camera", "Two-view observer stopped", None)

    def _capture_right_over_ssh(self) -> bytes:
        return self._capture_base64_over_ssh(
            build_mark_right_capture_command(),
            label="Mark RGB webcam",
        )

    def _capture_wrist_over_ssh(self) -> bytes:
        return self._capture_base64_over_ssh(
            build_mark_wrist_capture_command(),
            label="Mark DaBai",
        )

    def _capture_base64_over_ssh(self, command: str, *, label: str) -> bytes:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                self._host,
                command,
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"{label} capture failed: {detail or f'exit status {result.returncode}'}"
            )
        try:
            return base64.b64decode(result.stdout, validate=True)
        except ValueError as exc:
            raise RuntimeError(f"{label} capture returned invalid base64") from exc
