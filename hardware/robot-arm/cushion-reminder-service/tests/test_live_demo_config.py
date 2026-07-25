from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def test_lan_demo_broker_exposes_tcp_and_websocket_on_the_same_broker() -> None:
    config = (SERVICE_ROOT / "config" / "broker.lan-demo.yaml").read_text()

    assert "bind: 0.0.0.0:1883" in config
    assert "bind: 0.0.0.0:9001" in config
    assert "allow_anonymous: true" in config


def test_live_demo_uses_loopback_for_its_local_subscriber() -> None:
    script = (SERVICE_ROOT / "scripts" / "start-live-demo.sh").read_text()

    assert 'MQTT_HOST="${MQTT_HOST:-127.0.0.1}"' in script
    assert 'MQTT_PORT="${MQTT_PORT:-1883}"' in script
    assert "broker.lan-demo.yaml" in script
    assert "relay_policy_to_mark.sh" in script
    assert 'runtime_env="${CUSHION_RUNTIME_ENV:-${HOME}/.config/cushion-reminder/runtime.env}"' in script
    assert 'source "${runtime_env}"' in script
    assert "Runtime env must not be group/world readable" in script


def test_boundary_camera_publisher_never_accesses_mac_camera() -> None:
    script = (SERVICE_ROOT / "scripts" / "publish-two-view-frames.sh").read_text()

    assert "avfoundation" not in script
    assert "exterior_left" not in script
    assert "exterior_right" in script


def test_stop_script_holds_the_arm_before_stopping_demo_services() -> None:
    script = (SERVICE_ROOT / "scripts" / "stop-live-demo.sh").read_text()

    stop_position = script.index('tools/a1zctl" stop')
    service_position = script.index("cushion-mqtt-live")
    assert stop_position < service_position
    assert "test -S /tmp/a1z.sock" in script
    assert "Cannot confirm A1Z safe stop" in script
    assert "exit 2" in script
