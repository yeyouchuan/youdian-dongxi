from cushion_reminder.hardware import parse_probe_output


def test_probe_reports_the_exact_failed_live_motion_gates() -> None:
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
@@DEVICE_DETAILS
@@STABLE_LINKS
@@USB
Bus 001 Device 005: ID a8fa:8598 CANFD Analyser
@@USBIP
"""

    snapshot = parse_probe_output(raw)

    assert snapshot["healthy"] is False
    assert snapshot["failures"] == ["camera /dev/video* missing"]


def test_probe_blocks_dead_daemon_control_thread_and_motor_fault() -> None:
    raw = """@@HOST
Mark
@@SOCKET
present
@@DAEMON_STATUS
control_thread_alive=false
estopped=true
error_codes=[0,0,0,9,1,1]
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
@@STABLE_LINKS
@@USB
@@USBIP
"""

    snapshot = parse_probe_output(raw)

    assert snapshot["healthy"] is False
    assert "A1Z safe daemon control thread is not healthy" in snapshot["failures"]
    assert "A1Z safe daemon is emergency-stopped" in snapshot["failures"]
    assert "A1Z motor error codes are unsafe: [0, 0, 0, 9, 1, 1]" in snapshot["failures"]


def test_probe_blocks_new_motion_when_motor_temperature_is_too_high() -> None:
    raw = """@@HOST
Mark
@@SOCKET
present
@@DAEMON_STATUS
control_thread_alive=true
estopped=false
error_codes=[0,0,0,1,1,1]
temp_mos_c=[39,43,70,37,28,26]
temp_rotor_c=[31,34,89,35,35,35]
@@RELAY
present
@@CAN
can0 UP
can state ERROR-ACTIVE
bitrate 1000000
@@NODES
/dev/video0
@@DEVICE_DETAILS
@@STABLE_LINKS
@@USB
@@USBIP
"""

    snapshot = parse_probe_output(raw)

    assert snapshot["healthy"] is False
    assert "A1Z MOS temperature 70.0C exceeds 70.0C motion limit" in snapshot["failures"]
