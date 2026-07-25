from __future__ import annotations

from cushion_reminder.camera_capture import (
    SshMarkObservationAdapter,
    build_mark_right_capture_command,
    build_mark_wrist_capture_command,
)
from cushion_reminder.vision import REQUIRED_MANIPULATION_VIEWS, CameraView, FrameStore


def jpeg(payload: bytes = b"x" * 124) -> bytes:
    return b"\xff\xd8" + payload + b"\xff\xd9\x00"


def test_wrist_capture_command_resolves_dabai_identity_not_video_number() -> None:
    command = build_mark_wrist_capture_command()

    assert '"2bc5:0557"' in command
    assert "usbipd" in command
    assert "attach --wsl --busid" in command
    assert "detach --busid" not in command
    assert "ID_VENDOR_ID=2bc5" in command
    assert "ID_MODEL_ID=0557" in command
    assert "for node in /dev/video*" in command
    assert "for wait_attempt in 1 2 3 4 5 6 7 8 9 10" in command
    assert "for attempt in 1 2 3" in command
    assert 'test "$captured" = 1' in command
    assert "/dev/video0" not in command
    assert "base64 -w0" in command


def test_right_capture_attaches_once_and_keeps_device_for_boundary_snapshots() -> None:
    command = build_mark_right_capture_command()

    assert '"0408:30c3"' in command
    assert "usbipd" in command
    assert "attach --wsl --busid" in command
    assert "detach --busid" not in command
    assert "ID_VENDOR_ID=0408" in command
    assert "ID_MODEL_ID=30c3" in command
    assert "/tmp/a1z-vision/exterior-right.jpg" in command
    assert "2-7" not in command


def test_observer_pairs_mark_external_with_fresh_wrist_capture() -> None:
    store = FrameStore()
    events = []
    observer = SshMarkObservationAdapter(
        frame_store=store,
        capture_right=lambda: jpeg(b"right" * 32),
        capture_wrist=lambda: jpeg(),
    )

    observer.start(lambda level, message, data: events.append((level, message, data)))
    observation = observer.observe(
        phase="before",
        log=lambda level, message, data: events.append((level, message, data)),
    )
    observer.stop(lambda level, message, data: events.append((level, message, data)))

    assert set(observation.frames) == set(REQUIRED_MANIPULATION_VIEWS)
    assert (
        observation.frames[CameraView.EXTERIOR_RIGHT].source
        == "mark-webcam-0408:30c3-boundary"
    )
    assert observation.frames[CameraView.WRIST].orientation_degrees == 180
    assert any("before observation" in message for _, message, _ in events)
