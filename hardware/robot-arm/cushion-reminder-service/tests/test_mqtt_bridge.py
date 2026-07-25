from __future__ import annotations

import json

import paho.mqtt.client as mqtt

from cushion_reminder.mqtt_bridge import CushionMqttBridge, SeatedStateTracker
from cushion_reminder.simulator import POSTURE_TOPIC, RADAR_TOPIC


def test_continuous_occupied_posture_triggers_once_at_threshold() -> None:
    tracker = SeatedStateTracker(threshold_seconds=60)

    first = tracker.ingest({"pose": "UPRIGHT"}, now=100.0)
    before = tracker.ingest({"pose": "LEAN_L"}, now=159.9)
    reached = tracker.ingest({"pose": "UPRIGHT"}, now=160.0)
    repeated = tracker.ingest({"pose": "UPRIGHT"}, now=170.0)

    assert first.as_dict() == {
        "pose": "UPRIGHT",
        "occupied": True,
        "seated_seconds": 0.0,
        "threshold_seconds": 60.0,
        "threshold_reached": False,
        "new_trigger": False,
    }
    assert before.new_trigger is False
    assert reached.new_trigger is True
    assert repeated.threshold_reached is True
    assert repeated.new_trigger is False


def test_away_resets_session_and_allows_next_trigger() -> None:
    tracker = SeatedStateTracker(threshold_seconds=60)
    tracker.ingest({"pose": "UPRIGHT"}, now=100.0)
    assert tracker.ingest({"pose": "UPRIGHT"}, now=160.0).new_trigger is True

    away = tracker.ingest({"pose": "AWAY"}, now=161.0)
    restarted = tracker.ingest({"pose": "EDGE"}, now=200.0)
    retriggered = tracker.ingest({"pose": "EDGE"}, now=260.0)

    assert away.occupied is False
    assert away.seated_seconds == 0
    assert restarted.new_trigger is False
    assert retriggered.new_trigger is True


def test_simulated_elapsed_time_can_drive_full_mqtt_test_without_waiting() -> None:
    tracker = SeatedStateTracker(threshold_seconds=60)

    decision = tracker.ingest(
        {
            "pose": "UPRIGHT",
            "simulated": True,
            "effective_seated_seconds": 60,
        },
        now=100.0,
    )

    assert decision.seated_seconds == 60
    assert decision.new_trigger is True


def test_receiver_triggers_robot_callback_from_posture_topic() -> None:
    triggered: list[dict[str, object]] = []
    bridge = CushionMqttBridge(
        host="127.0.0.1",
        port=1883,
        threshold_seconds=60,
        on_threshold=lambda decision: triggered.append(decision.as_dict()),
    )

    bridge.ingest_message(
        POSTURE_TOPIC,
        json.dumps(
            {
                "pose": "UPRIGHT",
                "simulated": True,
                "effective_seated_seconds": 60,
            }
        ).encode(),
        now=100.0,
    )

    assert len(triggered) == 1
    status = bridge.status()
    assert status["occupied"] is True
    assert status["seated_seconds"] == 60
    assert status["last_posture"]["pose"] == "UPRIGHT"
    messages = [event["message"] for event in bridge.events_after(0)]
    assert "MQTT posture received" in messages
    assert "Continuous-sitting threshold reached" in messages


def test_receiver_records_filtered_radar_values_without_triggering_robot() -> None:
    triggered: list[dict[str, object]] = []
    bridge = CushionMqttBridge(
        host="127.0.0.1",
        port=1883,
        threshold_seconds=60,
        on_threshold=lambda decision: triggered.append(decision.as_dict()),
    )

    bridge.ingest_message(
        RADAR_TOPIC,
        b'{"heart":97,"heart_med":110,"breath":2,"breath_med":17,"dist":68.9,"seq":88}',
        now=100.0,
    )

    assert triggered == []
    status = bridge.status()
    assert status["last_radar"]["heart_med"] == 110
    assert status["last_radar"]["breath_med"] == 17


def test_busy_robot_submission_retries_after_cooldown() -> None:
    attempts: list[int] = []

    def trigger(_decision: object) -> None:
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RuntimeError("robot job is already active")

    bridge = CushionMqttBridge(
        host="127.0.0.1",
        port=1883,
        threshold_seconds=60,
        on_threshold=trigger,
    )
    payload = b'{"pose":"UPRIGHT","simulated":true,"effective_seated_seconds":60}'

    bridge.ingest_message(POSTURE_TOPIC, payload, now=100.0)
    bridge.ingest_message(POSTURE_TOPIC, payload, now=101.0)
    bridge.ingest_message(POSTURE_TOPIC, payload, now=106.0)

    assert attempts == [1, 2]
    messages = [event["message"] for event in bridge.events_after(0)]
    assert "Robot reminder trigger rejected" in messages
    assert "Robot reminder job created" in messages


def test_websocket_transport_is_passed_to_paho_and_reported(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def reconnect_delay_set(self, **kwargs: object) -> None:
            captured["reconnect"] = kwargs

        def connect_async(self, host: str, port: int, keepalive: int) -> None:
            captured["connect"] = (host, port, keepalive)

        def loop_start(self) -> None:
            captured["loop_started"] = True

    monkeypatch.setattr(mqtt, "Client", FakeClient)
    bridge = CushionMqttBridge(
        host="broker.local",
        port=9001,
        transport="websockets",
        threshold_seconds=60,
        on_threshold=lambda _decision: None,
    )

    bridge.start()

    assert captured["transport"] == "websockets"
    assert captured["connect"] == ("broker.local", 9001, 30)
    assert bridge.status()["transport"] == "websockets"
