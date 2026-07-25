from __future__ import annotations

import json
import shlex
import time
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from cushion_reminder.execution import (
    ExecutionResult,
    ShadowRobotExecutor,
    build_mark_remote_command,
    build_mark_return_neutral_command,
    build_mark_return_zero_command,
    parse_headless_step,
)
from cushion_reminder.hardware import parse_probe_output
from cushion_reminder.jobs import simulated_seated_threshold_event
from cushion_reminder.manual_control import (
    ShadowManualControl,
    build_mark_manual_jog_command,
    build_mark_manual_set_command,
)
from cushion_reminder.scenarios import SCENARIOS
from cushion_reminder.web import create_app, env_flag


class FakeHardwareProbe:
    def snapshot(self) -> dict[str, Any]:
        return {
            "host": "Mark",
            "healthy": True,
            "a1z_socket": True,
            "policy_relay": True,
            "can": ["can0 UP", "can state ERROR-ACTIVE", "bitrate 1000000"],
            "device_nodes": ["/dev/video0", "/dev/video1"],
            "device_details": ["/dev/video0 VID:PID=2bc5:0557 serial=CC1N16200WR model=Dabai_DC1"],
            "stable_links": ["/dev/v4l/by-id/usb-DaBai -> ../../video0"],
            "usb_devices": [
                "Bus 001 Device 003: ID 2bc5:0557 DaBai DC1",
                "Bus 001 Device 005: ID a8fa:8598 CANFD Analyser",
            ],
            "usbip": [],
        }


def valid_camera_geometry_json() -> str:
    def transform(x: float, y: float, z: float) -> list[list[float]]:
        return [
            [1.0, 0.0, 0.0, x],
            [0.0, 1.0, 0.0, y],
            [0.0, 0.0, 1.0, z],
            [0.0, 0.0, 0.0, 1.0],
        ]

    intrinsics = {
        "width": 640,
        "height": 480,
        "fx": 520.0,
        "fy": 520.0,
        "cx": 320.0,
        "cy": 240.0,
    }
    return json.dumps(
        {
            "calibration_id": "demo-001",
            "coordinate_frame": "a1z_base",
            "views": {
                "exterior_right": {
                    "parent_frame": "a1z_base",
                    "parent_from_camera": transform(0.35, -0.25, 0.45),
                    "intrinsics": intrinsics,
                    "orientation_degrees": 0,
                    "reprojection_error_px": 1.2,
                },
                "wrist": {
                    "parent_frame": "arm_link6",
                    "parent_from_camera": transform(0.0, 0.0, 0.08),
                    "intrinsics": intrinsics,
                    "orientation_degrees": 180,
                    "reprojection_error_px": 1.2,
                }
            },
        }
    )


class UnhealthyHardwareProbe(FakeHardwareProbe):
    def snapshot(self) -> dict[str, Any]:
        snapshot = super().snapshot()
        snapshot["healthy"] = False
        snapshot["policy_relay"] = False
        return snapshot


class RecordingLiveExecutor:
    mode = "ssh-mark"

    def __init__(self) -> None:
        self.called = False

    def execute(self, scenario, log) -> ExecutionResult:
        self.called = True
        return ExecutionResult(steps_requested=scenario.max_steps, mode=self.mode)


class FakeMqttBridge:
    def __init__(self) -> None:
        self.published: list[str] = []

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {
            "host": "127.0.0.1",
            "port": 1883,
            "connected": True,
            "topic_filter": "zuodian/#",
            "threshold_seconds": 60,
            "pose": "UPRIGHT",
            "occupied": True,
            "seated_seconds": 12,
            "threshold_reached": False,
            "last_posture": {"pose": "UPRIGHT"},
            "last_radar": {"heart_med": 82, "breath_med": 16},
            "event_count": 1,
        }

    def events_after(self, after: int) -> list[dict[str, Any]]:
        if after >= 1:
            return []
        return [
            {
                "sequence": 1,
                "at": "2026-07-25T00:00:00+00:00",
                "level": "mqtt",
                "message": "MQTT posture received",
                "data": {"pose": "UPRIGHT"},
            }
        ]

    def publish_test_event(self, kind: str) -> dict[str, Any]:
        self.published.append(kind)
        if kind not in {"occupied", "continuous-seated", "away", "radar"}:
            raise KeyError(kind)
        return {"topic": "zuodian/posture", "payload": {"pose": "UPRIGHT"}}


def test_simulated_threshold_event_represents_one_hour() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

    event = simulated_seated_threshold_event(now=now)

    assert event["topic"] == "zuodian/posture"
    assert event["pose"] == "UPRIGHT"
    assert event["effective_seated_seconds"] == 3600
    assert event["reason"] == "continuous_seated_60m"


def test_no_scenario_allows_human_contact() -> None:
    assert SCENARIOS
    for scenario in SCENARIOS.values():
        assert scenario.intent_type
        assert scenario.trigger_kind in {"continuous_seated_60m", "manual_test"}
        assert "Do not" in scenario.prompt
        assert "touch any person" in scenario.prompt or "touch the person" in scenario.prompt


def test_mark_command_uses_only_allowlisted_scenario_values() -> None:
    scenario = SCENARIOS["seated_60m_non_contact_reminder"]

    command = build_mark_remote_command(scenario)

    assert "test -S /tmp/a1z.sock" in command
    assert 'python_path="$HOME/GALAXEA-A1Z/.venv/bin/python"' in command
    assert "timeout --signal=TERM --kill-after=5s 175s" in command
    assert "PYTHONUNBUFFERED=1" in command
    assert shlex.quote(scenario.prompt) in command
    assert "--max-steps 64" in command
    assert "config.mark-execute.yaml" in command


def test_return_neutral_command_is_fixed_and_uses_safe_daemon() -> None:
    command = build_mark_return_neutral_command()

    assert "test -S /tmp/a1z.sock" in command
    assert '"$HOME/GALAXEA-A1Z/tools/a1zctl"' in command
    assert "move 0,60,-60,0,0,0 --speed 0.15" in command
    assert "timeout --signal=TERM --kill-after=5s 55s" in command


def test_return_zero_command_is_fixed_and_uses_safe_daemon() -> None:
    command = build_mark_return_zero_command()

    assert "test -S /tmp/a1z.sock" in command
    assert '"$HOME/GALAXEA-A1Z/tools/a1zctl"' in command
    assert "move 0,0,0,0,0,0 --speed 0.15" in command
    assert "timeout --signal=TERM --kill-after=5s 55s" in command


def test_manual_jog_command_only_moves_the_selected_allowlisted_joint() -> None:
    command = build_mark_manual_jog_command("j5", -1)

    assert "test -S /tmp/a1z.sock" in command
    assert "p[4]+=(-2)" in command
    assert "speed" in command
    assert "0.1" in command
    assert "move" in command


def test_manual_set_command_uses_absolute_value_for_allowlisted_joint() -> None:
    command = build_mark_manual_set_command("j5", 12.5)

    assert "p[4]=12.5" in command
    assert "speed" in command
    assert "move" in command


def test_each_scenario_selects_its_declared_mark_camera_config() -> None:
    for scenario in SCENARIOS.values():
        command = build_mark_remote_command(scenario)
        assert scenario.camera_profile.mark_config_name in command

    assert (
        SCENARIOS["approach_foam_target"].camera_profile.mark_config_name
        == "config.mark-execute-two-view.yaml"
    )
    assert (
        SCENARIOS["locate_person_non_contact_gesture"].camera_profile.mark_config_name
        == "config.mark-execute-two-view.yaml"
    )
    assert (
        SCENARIOS["grasp_lightweight_test_object"].camera_profile.mark_config_name
        == "config.mark-execute-two-view.yaml"
    )


def test_headless_step_line_is_parsed_for_structured_live_log() -> None:
    parsed = parse_headless_step("step=12 hz=14.9 need_obs=False error=-")

    assert parsed == {
        "step": 12,
        "hz": 14.9,
        "need_observation": False,
        "error": None,
    }
    assert parse_headless_step("2026 INFO camera started") is None


def test_probe_output_is_split_into_debug_sections() -> None:
    raw = """@@HOST
Mark
@@SOCKET
present
@@DAEMON_STATUS
control_thread_alive=true
estopped=false
error_codes=[0,0,0,1,1,1]
temp_mos_c=[39,43,57,37,28,26]
temp_rotor_c=[31,34,56.5,35,35,35]
@@RELAY
present
@@CAN
can0 UP
can state ERROR-ACTIVE
bitrate 1000000
@@NODES
/dev/video0
@@DEVICE_DETAILS
/dev/video0 VID:PID=2bc5:0557 serial=CC1 model=Dabai
@@STABLE_LINKS
/dev/v4l/by-id/dabai -> ../../video0
@@USB
Bus 001 Device 003: ID 2bc5:0557 DaBai DC1
@@USBIP
Port 00: <Port in Use>
"""

    snapshot = parse_probe_output(raw)

    assert snapshot["host"] == "Mark"
    assert snapshot["healthy"] is True
    assert "VID:PID=2bc5:0557" in snapshot["device_details"][0]
    assert snapshot["usb_devices"][0].startswith("Bus 001 Device 003")


def test_web_api_triggers_shadow_workflow_and_streams_events() -> None:
    client = TestClient(
        create_app(executor=ShadowRobotExecutor(), hardware_probe=FakeHardwareProbe())
    )

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["execution_mode"] == "shadow"
    assert status.json()["human_contact_enabled"] is False
    assert status.json()["exterior_camera_ready"] is False
    assert status.json()["mounted_as_exterior_ready"] is False
    hardware = client.get("/api/hardware")
    assert hardware.status_code == 200
    assert hardware.json()["healthy"] is True
    assert hardware.json()["usb_devices"][0].find("2bc5:0557") >= 0

    response = client.post("/api/scenarios/seated_60m_non_contact_reminder/trigger")
    assert response.status_code == 202
    job_id = response.json()["id"]

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)

    assert job["status"] == "succeeded"
    events = client.get(f"/api/jobs/{job_id}/events?after=0").json()
    messages = [event["message"] for event in events]
    assert any(message.endswith("continuous-sitting threshold event") for message in messages)
    assert any(message.endswith("Created allowlisted RobotIntent") for message in messages)
    assert "Shadow mode: DGX request and A1Z motion were not sent" in messages
    assert any(message.endswith("Scenario workflow completed") for message in messages)


def test_mqtt_continuous_seated_sample_creates_and_completes_robot_job() -> None:
    app = create_app(
        executor=ShadowRobotExecutor(),
        hardware_probe=FakeHardwareProbe(),
        exterior_camera_ready=True,
    )
    client = TestClient(app)

    app.state.mqtt_bridge.ingest_message(
        "zuodian/posture",
        b'{"pose":"UPRIGHT","simulated":true,"effective_seated_seconds":60}',
        now=100.0,
    )

    mqtt_events = app.state.mqtt_bridge.events_after(0)
    created = next(
        event for event in mqtt_events if event["message"] == "Robot reminder job created"
    )
    job_id = created["data"]["id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)

    assert job["status"] == "succeeded"
    assert job["scenario_id"] == "locate_person_non_contact_gesture"
    events = client.get(f"/api/jobs/{job_id}/events?after=0").json()
    assert any("Received MQTT continuous-sitting" in event["message"] for event in events)
    assert any("Created allowlisted RobotIntent" in event["message"] for event in events)


def test_web_api_returns_robot_to_fixed_neutral_pose() -> None:
    client = TestClient(
        create_app(executor=ShadowRobotExecutor(), hardware_probe=FakeHardwareProbe())
    )

    response = client.post("/api/commands/return-neutral")

    assert response.status_code == 202
    job_id = response.json()["id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)

    assert job["status"] == "succeeded"
    assert job["scenario_id"] == "return_neutral"
    events = client.get(f"/api/jobs/{job_id}/events?after=0").json()
    assert any(
        event["data"] and event["data"].get("target_degrees") == [0, 60, -60, 0, 0, 0]
        for event in events
    )
    assert any("deterministic neutral pose" in event["message"] for event in events)


def test_console_exposes_return_neutral_button() -> None:
    client = TestClient(create_app(executor=ShadowRobotExecutor()))

    response = client.get("/")

    assert response.status_code == 200
    assert "回到中立位" in response.text
    assert "/api/commands/return-neutral" in response.text


def test_console_exposes_j3_cooldown_zero_pose_button() -> None:
    client = TestClient(create_app(executor=ShadowRobotExecutor()))

    response = client.get("/")

    assert response.status_code == 200
    assert "J3 降温零位" in response.text
    assert "/api/commands/return-zero" in response.text


def test_web_api_returns_robot_to_fixed_zero_pose() -> None:
    client = TestClient(
        create_app(executor=ShadowRobotExecutor(), hardware_probe=FakeHardwareProbe())
    )

    response = client.post("/api/commands/return-zero")

    assert response.status_code == 202
    job_id = response.json()["id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)

    assert job["status"] == "succeeded"
    assert job["scenario_id"] == "return_zero"
    events = client.get(f"/api/jobs/{job_id}/events?after=0").json()
    assert any(
        event["data"] and event["data"].get("target_degrees") == [0, 0, 0, 0, 0, 0]
        for event in events
    )


def test_console_exposes_five_axis_and_gripper_manual_controls() -> None:
    client = TestClient(
        create_app(executor=ShadowRobotExecutor(), hardware_probe=FakeHardwareProbe())
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "API 操控测试" in response.text
    assert "/api/manual-control/jog" in response.text
    assert "/api/manual-control/set" in response.text
    assert "{id:'j5', label:'轴 4', jointIndex:4, min:-85, max:85}" in response.text
    assert "class=\"joint-value\" type=\"number\"" in response.text


def test_manual_control_api_jogs_shadow_joint_and_gripper() -> None:
    manual = ShadowManualControl()
    client = TestClient(
        create_app(
            executor=ShadowRobotExecutor(),
            hardware_probe=FakeHardwareProbe(),
            manual_controller=manual,
        )
    )

    initial = client.get("/api/manual-control")
    joint = client.post(
        "/api/manual-control/jog",
        json={"control": "j1", "direction": 1},
    )
    gripper = client.post(
        "/api/manual-control/jog",
        json={"control": "gripper", "direction": -1},
    )

    assert initial.status_code == 200
    assert initial.json()["joints_degrees"][0] == 0
    assert joint.status_code == 200
    assert joint.json()["joints_degrees"][0] == 2
    assert gripper.status_code == 200
    assert gripper.json()["gripper"] == 0.9


def test_manual_control_api_sets_absolute_shadow_values() -> None:
    manual = ShadowManualControl()
    client = TestClient(
        create_app(
            executor=ShadowRobotExecutor(),
            hardware_probe=FakeHardwareProbe(),
            manual_controller=manual,
        )
    )

    joint = client.post(
        "/api/manual-control/set",
        json={"control": "j5", "value": 12.5},
    )
    gripper = client.post(
        "/api/manual-control/set",
        json={"control": "gripper", "value": 0.35},
    )

    assert joint.status_code == 200
    assert joint.json()["joints_degrees"][4] == 12.5
    assert gripper.status_code == 200
    assert gripper.json()["gripper"] == 0.35


def test_manual_control_api_rejects_absolute_value_outside_limits() -> None:
    client = TestClient(
        create_app(executor=ShadowRobotExecutor(), hardware_probe=FakeHardwareProbe())
    )

    response = client.post(
        "/api/manual-control/set",
        json={"control": "j5", "value": 90},
    )

    assert response.status_code == 422


def test_manual_control_api_rejects_locked_or_invalid_controls() -> None:
    client = TestClient(
        create_app(executor=ShadowRobotExecutor(), hardware_probe=FakeHardwareProbe())
    )

    locked = client.post(
        "/api/manual-control/jog",
        json={"control": "j4", "direction": 1},
    )
    invalid_direction = client.post(
        "/api/manual-control/jog",
        json={"control": "j1", "direction": 2},
    )

    assert locked.status_code == 422
    assert invalid_direction.status_code == 422


def test_console_exposes_mqtt_layer_and_test_api() -> None:
    mqtt = FakeMqttBridge()
    client = TestClient(create_app(executor=ShadowRobotExecutor(), mqtt_bridge=mqtt))

    page = client.get("/")
    status = client.get("/api/mqtt/status")
    events = client.get("/api/mqtt/events?after=0")
    published = client.post("/api/mqtt/test/continuous-seated")

    assert page.status_code == 200
    assert "MQTT 坐垫事件" in page.text
    assert "/api/mqtt/test/continuous-seated" in page.text
    assert status.json()["threshold_seconds"] == 60
    assert events.json()[0]["message"] == "MQTT posture received"
    assert published.status_code == 202
    assert mqtt.published == ["continuous-seated"]


def test_unknown_scenario_returns_404() -> None:
    client = TestClient(create_app(executor=ShadowRobotExecutor()))

    response = client.post("/api/scenarios/does-not-exist/trigger")

    assert response.status_code == 404


def test_unhealthy_mark_preflight_blocks_live_executor() -> None:
    executor = RecordingLiveExecutor()
    client = TestClient(create_app(executor=executor, hardware_probe=UnhealthyHardwareProbe()))

    response = client.post("/api/scenarios/seated_60m_non_contact_reminder/trigger")
    job_id = response.json()["id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)

    assert job["status"] == "failed"
    assert executor.called is False
    events = client.get(f"/api/jobs/{job_id}/events?after=0").json()
    assert any(event["level"] == "hardware" for event in events)
    assert any("hardware preflight failed" in event["message"] for event in events)


def test_non_grasp_scenarios_reach_live_executor_when_camera_profile_is_ready(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ALLOW_MOUNTED_AS_EXTERIOR", "1")
    for scenario_id, scenario in SCENARIOS.items():
        if scenario.intent_type == "grasp_test_object":
            continue
        executor = RecordingLiveExecutor()
        client = TestClient(
            create_app(
                executor=executor,
                hardware_probe=FakeHardwareProbe(),
                exterior_camera_ready=True,
            )
        )
        response = client.post(f"/api/scenarios/{scenario_id}/trigger")
        job_id = response.json()["id"]

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)

        assert job["status"] == "succeeded", scenario_id
        assert executor.called is True, scenario_id


def test_live_grasp_is_blocked_without_two_view_gpt_evaluator() -> None:
    executor = RecordingLiveExecutor()
    client = TestClient(
        create_app(
            executor=executor,
            hardware_probe=FakeHardwareProbe(),
            exterior_camera_ready=True,
        )
    )

    response = client.post("/api/scenarios/grasp_lightweight_test_object/trigger")
    job_id = response.json()["id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)

    assert job["status"] == "failed"
    assert executor.called is False
    events = client.get(f"/api/jobs/{job_id}/events?after=0").json()
    assert any("GPT-5.6 evaluation is not configured" in event["message"] for event in events)


def test_live_service_requires_calibrated_geometry_and_opt_in_for_gpt_actuators(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    incomplete_client = TestClient(
        create_app(
            executor=RecordingLiveExecutor(),
            hardware_probe=FakeHardwareProbe(),
        )
    )

    incomplete = incomplete_client.get("/api/status").json()

    assert incomplete["gpt_visual_evaluator_ready"] is True
    assert incomplete["gpt_actuator_correction_ready"] is False

    monkeypatch.setenv("ENABLE_GPT_ACTUATOR_TOOLS", "1")
    monkeypatch.setenv("A1Z_CAMERA_GEOMETRY", valid_camera_geometry_json())
    ready_client = TestClient(
        create_app(
            executor=RecordingLiveExecutor(),
            hardware_probe=FakeHardwareProbe(),
        )
    )
    ready = ready_client.get("/api/status").json()

    assert ready["gpt_visual_evaluator_ready"] is True
    assert ready["gpt_actuator_correction_ready"] is True
    assert ready["camera_geometry_ready"] is True
    assert ready["camera_observation_mode"] == "action-boundary"
    assert ready["required_camera_views"] == [
        "exterior_right",
        "wrist",
    ]


def test_invalid_camera_geometry_fails_closed_without_crashing_service(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_GPT_ACTUATOR_TOOLS", "1")
    monkeypatch.setenv("A1Z_CAMERA_GEOMETRY", '{"calibration_id":"broken"}')
    client = TestClient(
        create_app(
            executor=RecordingLiveExecutor(),
            hardware_probe=FakeHardwareProbe(),
        )
    )

    status = client.get("/api/status").json()
    readiness = client.get("/api/readiness").json()

    assert status["gpt_actuator_correction_ready"] is False
    assert status["camera_geometry_ready"] is False
    assert "camera geometry invalid" in status["camera_geometry_error"]
    assert any(
        "camera geometry invalid" in blocker
        for blocker in readiness["capabilities"]["gpt_actuator_correction"]["blockers"]
    )


def test_mounted_as_exterior_requires_explicit_live_opt_in() -> None:
    executor = RecordingLiveExecutor()
    client = TestClient(create_app(executor=executor, hardware_probe=FakeHardwareProbe()))

    response = client.post("/api/scenarios/approach_foam_target/trigger")
    job_id = response.json()["id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.01)

    assert job["status"] == "failed"
    assert executor.called is False


def test_env_flag_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("EXTERIOR_CAMERA_READY", "true")
    assert env_flag("EXTERIOR_CAMERA_READY") is True
    monkeypatch.setenv("EXTERIOR_CAMERA_READY", "not-sure")
    assert env_flag("EXTERIOR_CAMERA_READY") is False


def test_manual_scenario_does_not_claim_a_continuous_sitting_trigger() -> None:
    client = TestClient(create_app(executor=ShadowRobotExecutor()))
    response = client.post("/api/scenarios/approach_foam_target/trigger")
    job_id = response.json()["id"]

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        events = client.get(f"/api/jobs/{job_id}/events?after=0").json()
        if any(event["message"].endswith("Scenario workflow completed") for event in events):
            break
        time.sleep(0.01)

    messages = [event["message"] for event in events]
    assert any(message.endswith("manual test scenario trigger") for message in messages)
    assert not any(message.endswith("continuous-sitting threshold event") for message in messages)
