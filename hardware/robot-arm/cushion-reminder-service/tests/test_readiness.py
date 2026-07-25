from fastapi.testclient import TestClient

from cushion_reminder.execution import ShadowRobotExecutor
from cushion_reminder.readiness import build_readiness
from cushion_reminder.web import create_app


class FakeMqtt:
    def __init__(self, *, connected: bool) -> None:
        self.connected = connected

    def status(self) -> dict[str, object]:
        return {
            "host": "127.0.0.1",
            "port": 1883,
            "transport": "tcp",
            "connected": self.connected,
        }

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def events_after(self, _after: int) -> list[dict[str, object]]:
        return []

    def publish_test_event(self, _kind: str) -> dict[str, object]:
        return {}


class FakeHardware:
    def __init__(self, *, healthy: bool, failures: list[str]) -> None:
        self.healthy = healthy
        self.failures = failures

    def snapshot(self) -> dict[str, object]:
        return {
            "host": "Mark",
            "healthy": self.healthy,
            "failures": self.failures,
        }


def test_readiness_reports_every_blocker_before_live_motion() -> None:
    readiness = build_readiness(
        FakeMqtt(connected=False),
        FakeHardware(
            healthy=False,
            failures=[
                "DGX policy relay 127.0.0.1:8765 missing",
                "camera /dev/video* missing",
            ],
        ),
        execution_mode="ssh-mark",
        mounted_as_exterior_ready=True,
    )

    assert readiness["ready"] is False
    assert readiness["blockers"] == [
        "MQTT subscriber is disconnected",
        "DGX policy relay 127.0.0.1:8765 missing",
        "camera /dev/video* missing",
    ]


def test_readiness_is_true_only_when_mqtt_and_hardware_are_ready() -> None:
    readiness = build_readiness(
        FakeMqtt(connected=True),
        FakeHardware(healthy=True, failures=[]),
        execution_mode="ssh-mark",
        mounted_as_exterior_ready=True,
    )

    assert readiness["ready"] is True
    assert readiness["blockers"] == []


def test_readiness_rejects_shadow_or_missing_mounted_camera_opt_in() -> None:
    readiness = build_readiness(
        FakeMqtt(connected=True),
        FakeHardware(healthy=True, failures=[]),
        execution_mode="shadow",
        mounted_as_exterior_ready=False,
    )

    assert readiness["ready"] is False
    assert readiness["blockers"] == [
        "service execution mode is not ssh-mark",
        "mounted-as-exterior camera mode is not enabled",
    ]


def test_readiness_is_exposed_through_the_local_api() -> None:
    client = TestClient(
        create_app(
            executor=ShadowRobotExecutor(),
            mqtt_bridge=FakeMqtt(connected=True),
            hardware_probe=FakeHardware(healthy=True, failures=[]),
        )
    )

    response = client.get("/api/readiness")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["capabilities"]["base_motion"]["ready"] is True
    assert (
        response.json()["capabilities"]["two_view_grasp"]["ready"]
        is False
    )
    assert response.json()["capabilities"]["two_view_grasp"]["blockers"] == [
        "OPENAI_API_KEY is not configured",
        "GPT-5.6 manipulation workflow is not configured",
        "two-view camera observation is not ready",
    ]
    assert response.json()["capabilities"]["gpt_actuator_correction"]["blockers"] == [
        "OPENAI_API_KEY is not configured",
        "GPT actuator tools are not explicitly enabled",
        "calibrated A1Z camera geometry is not configured",
        "GPT actuator correction is not configured",
    ]
