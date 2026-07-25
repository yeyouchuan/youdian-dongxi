from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cushion_reminder.execution import ShadowRobotExecutor
from cushion_reminder.openai_evaluator import (
    EvaluationVerdict,
    OpenAIVisionEvaluator,
    Verdict,
)
from cushion_reminder.vision import (
    REQUIRED_MANIPULATION_VIEWS,
    CameraView,
    FrameStore,
    MissingCameraEvidence,
)
from cushion_reminder.web import create_app


def jpeg(payload: bytes = b"x" * 124) -> bytes:
    return b"\xff\xd8" + payload + b"\xff\xd9"


def populate_two_views(store: FrameStore, *, now: datetime) -> None:
    for view in REQUIRED_MANIPULATION_VIEWS:
        payload = (view.value.encode() * 32)[:124]
        store.put(
            view,
            jpeg(payload),
            captured_at=now,
            received_at=now,
            source=f"test:{view.value}",
            orientation_degrees=180 if view is CameraView.WRIST else 0,
        )


def test_frame_store_requires_both_fresh_views() -> None:
    now = datetime(2026, 7, 25, 1, 0, tzinfo=timezone.utc)
    store = FrameStore()
    store.put(
        CameraView.EXTERIOR_RIGHT,
        jpeg(),
        captured_at=now,
        received_at=now,
    )

    with pytest.raises(MissingCameraEvidence, match="wrist"):
        store.snapshot(now=now, max_age_seconds=3)

    populate_two_views(store, now=now)
    snapshot = store.snapshot(now=now + timedelta(seconds=2), max_age_seconds=3)
    assert set(snapshot.frames) == set(REQUIRED_MANIPULATION_VIEWS)
    assert store.status(now=now + timedelta(seconds=2))["ready"] is True


def test_frame_store_rejects_stale_or_invalid_frames() -> None:
    now = datetime(2026, 7, 25, 1, 0, tzinfo=timezone.utc)
    store = FrameStore()
    populate_two_views(store, now=now)

    with pytest.raises(MissingCameraEvidence, match="stale="):
        store.snapshot(now=now + timedelta(seconds=4), max_age_seconds=3)
    with pytest.raises(ValueError, match="complete JPEG"):
        store.put(CameraView.WRIST, b"not-a-jpeg" * 16)


class FakeResponses:
    def __init__(self) -> None:
        self.request = None

    def parse(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            output_parsed={
                "verdict": "success",
                "position_correct": True,
                "target_correct": True,
                "calibrated_descent_ready": False,
                "grasp_confirmed": True,
                "confidence": 0.91,
                "failure_code": "none",
                "evidence": ["The target is between both fingertips and above the table."],
                "next_subtask": "stop",
                "feedback": "The requested grasp and lift are visibly complete.",
                "requires_new_observation": False,
            }
        )


def test_openai_evaluator_sends_paired_two_view_images_and_parses_schema() -> None:
    now = datetime(2026, 7, 25, 1, 0, tzinfo=timezone.utc)
    before_store = FrameStore()
    after_store = FrameStore()
    populate_two_views(before_store, now=now)
    populate_two_views(after_store, now=now)
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    evaluator = OpenAIVisionEvaluator(client=client, model="gpt-5.6", detail="original")

    verdict = evaluator.evaluate(
        task="Pick up one white hand model and lift it.",
        target_description="the closest white hand model",
        subtask="verify grasp and lift",
        iteration=1,
        before=before_store.snapshot(now=now),
        after=after_store.snapshot(now=now),
    )

    assert isinstance(verdict, EvaluationVerdict)
    assert verdict.verdict is Verdict.SUCCESS
    assert responses.request["model"] == "gpt-5.6"
    user_content = responses.request["input"][1]["content"]
    images = [item for item in user_content if item["type"] == "input_image"]
    labels = [item["text"] for item in user_content if item["type"] == "input_text"]
    assert len(images) == 4
    assert all(image["detail"] == "original" for image in images)
    assert any("BEFORE view=exterior_right" in label for label in labels)
    assert any("AFTER view=wrist" in label for label in labels)
    assert not any("view=exterior_left" in label for label in labels)


def test_camera_api_reports_readiness_only_after_two_fresh_jpegs() -> None:
    store = FrameStore()
    client = TestClient(create_app(executor=ShadowRobotExecutor(), frame_store=store))

    assert client.get("/api/cameras/status").json()["ready"] is False
    for view in REQUIRED_MANIPULATION_VIEWS:
        response = client.post(
            f"/api/cameras/{view.value}/frame",
            content=jpeg(),
            headers={
                "content-type": "image/jpeg",
                "x-camera-source": f"test:{view.value}",
                "x-orientation-degrees": "180" if view is CameraView.WRIST else "0",
            },
        )
        assert response.status_code == 202

    status = client.get("/api/cameras/status").json()
    assert status["ready"] is True
    assert status["views"]["wrist"]["frame"]["orientation_degrees"] == 180
    latest = client.get("/api/cameras/exterior_right/frame")
    assert latest.status_code == 200
    assert latest.headers["content-type"] == "image/jpeg"
    assert latest.content == jpeg()


def test_camera_api_rejects_non_jpeg_and_console_exposes_two_view_capture() -> None:
    client = TestClient(create_app(executor=ShadowRobotExecutor()))

    rejected = client.post(
        "/api/cameras/exterior_left/frame",
        content=b"not an image",
        headers={"content-type": "text/plain"},
    )
    deprecated = client.post(
        "/api/cameras/exterior_left/frame",
        content=jpeg(),
        headers={"content-type": "image/jpeg"},
    )
    page = client.get("/")

    assert rejected.status_code == 415
    assert deprecated.status_code == 404
    assert "双视角视觉验收" in page.text
    assert "navigator.mediaDevices.getUserMedia" not in page.text
    assert "navigator.mediaDevices.enumerateDevices" not in page.text
    assert 'id="mac-camera-device"' not in page.text
    assert 'id="capture-two-views"' in page.text
    assert "/api/cameras/capture-two-view" in page.text
    assert "/api/cameras/exterior_left/frame" not in page.text


def test_two_view_boundary_capture_is_live_mode_only() -> None:
    client = TestClient(create_app(executor=ShadowRobotExecutor()))

    response = client.post("/api/cameras/capture-two-view")

    assert response.status_code == 409
    assert "requires ssh-mark" in response.json()["detail"]
