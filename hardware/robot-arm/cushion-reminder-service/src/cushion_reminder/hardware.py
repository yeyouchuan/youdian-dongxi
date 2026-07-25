"""Read-only Mark hardware probe for the local debugging console."""

from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from typing import Any, Protocol

_SECTIONS = {
    "HOST": "host",
    "SOCKET": "socket",
    "DAEMON_STATUS": "daemon_status",
    "RELAY": "relay",
    "CAN": "can",
    "NODES": "device_nodes",
    "DEVICE_DETAILS": "device_details",
    "STABLE_LINKS": "stable_links",
    "USB": "usb_devices",
    "USBIP": "usbip",
}
MAX_MOTION_MOS_TEMP_C = 70.0
MAX_MOTION_ROTOR_TEMP_C = 90.0

REMOTE_PROBE_COMMAND = r"""set +e
echo '@@HOST'
hostname
echo '@@SOCKET'
if test -S /tmp/a1z.sock; then echo present; else echo missing; fi
echo '@@DAEMON_STATUS'
if test -S /tmp/a1z.sock; then
python3 - <<'PY'
import json
import socket

try:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    sock.connect("/tmp/a1z.sock")
    sock.sendall(b'{"cmd":"status","args":{}}\n')
    payload = b""
    while b"\n" not in payload:
        chunk = sock.recv(4096)
        if not chunk:
            break
        payload += chunk
    response = json.loads(payload.split(b"\n", 1)[0])
    data = response["data"]
    for key in (
        "control_thread_alive",
        "estopped",
        "error_codes",
        "temp_mos_c",
        "temp_rotor_c",
        "pos_deg",
        "command_deg",
        "tracking_error_deg",
    ):
        print(f"{key}={json.dumps(data.get(key), separators=(',', ':'))}")
except Exception as exc:
    print(f"probe_error={json.dumps(type(exc).__name__ + ': ' + str(exc))}")
PY
fi
echo '@@RELAY'
if command -v ss >/dev/null 2>&1 && ss -ltn | grep -q '127.0.0.1:8765'; then
  echo present
else
  echo missing
fi
echo '@@CAN'
ip -brief link show can0 2>&1
ip -details link show can0 2>&1 | sed -n '1,8p'
echo '@@NODES'
for dev in /dev/video* /dev/ttyUSB* /dev/ttyACM*; do
  test -e "$dev" && ls -l "$dev"
done
echo '@@DEVICE_DETAILS'
for dev in /dev/video* /dev/ttyUSB* /dev/ttyACM*; do
  test -e "$dev" || continue
  properties="$(udevadm info --query=property --name="$dev" 2>/dev/null)"
  vendor="$(printf '%s\n' "$properties" | sed -n 's/^ID_VENDOR_ID=//p' | head -1)"
  product="$(printf '%s\n' "$properties" | sed -n 's/^ID_MODEL_ID=//p' | head -1)"
  serial="$(printf '%s\n' "$properties" | sed -n 's/^ID_SERIAL_SHORT=//p' | head -1)"
  model="$(printf '%s\n' "$properties" | sed -n 's/^ID_MODEL=//p' | head -1)"
  printf '%s VID:PID=%s:%s serial=%s model=%s\n' \
    "$dev" "${vendor:--}" "${product:--}" "${serial:--}" "${model:--}"
done
echo '@@STABLE_LINKS'
for directory in /dev/v4l/by-id /dev/serial/by-id; do
  test -d "$directory" && find "$directory" -maxdepth 1 -type l -exec ls -l {} \;
done
echo '@@USB'
command -v lsusb >/dev/null 2>&1 && lsusb
echo '@@USBIP'
command -v usbip >/dev/null 2>&1 && usbip port 2>&1
true
"""


class HardwareProbe(Protocol):
    def snapshot(self) -> dict[str, Any]: ...


def parse_probe_output(raw: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = {name: [] for name in _SECTIONS.values()}
    current: str | None = None
    for untrimmed in raw.splitlines():
        line = untrimmed.strip()
        if line.startswith("@@"):
            current = _SECTIONS.get(line[2:])
            continue
        if current is not None and line:
            sections[current].append(line)

    host = sections["host"][0] if sections["host"] else "unknown"
    socket_present = sections["socket"][:1] == ["present"]
    daemon_status: dict[str, Any] = {}
    for line in sections["daemon_status"]:
        key, separator, value = line.partition("=")
        if not separator:
            continue
        try:
            daemon_status[key] = json.loads(value)
        except json.JSONDecodeError:
            daemon_status[key] = value
    daemon_healthy = (
        socket_present
        and daemon_status.get("control_thread_alive") is True
        and daemon_status.get("estopped") is False
        and "probe_error" not in daemon_status
    )
    error_codes = daemon_status.get("error_codes")
    if isinstance(error_codes, list):
        daemon_healthy = daemon_healthy and all(
            isinstance(code, (int, float)) and 0 <= code <= 1
            for code in error_codes
        )
    mos_temperatures = daemon_status.get("temp_mos_c")
    rotor_temperatures = daemon_status.get("temp_rotor_c")
    temperatures_valid = all(
        isinstance(values, list)
        and len(values) == 6
        and all(
            isinstance(value, (int, float)) and math.isfinite(float(value))
            for value in values
        )
        for values in (mos_temperatures, rotor_temperatures)
    )
    hottest_mos = (
        max(float(value) for value in mos_temperatures)
        if temperatures_valid
        else None
    )
    hottest_rotor = (
        max(float(value) for value in rotor_temperatures)
        if temperatures_valid
        else None
    )
    temperatures_safe = bool(
        temperatures_valid
        and hottest_mos is not None
        and hottest_mos < MAX_MOTION_MOS_TEMP_C
        and hottest_rotor is not None
        and hottest_rotor < MAX_MOTION_ROTOR_TEMP_C
    )
    daemon_healthy = daemon_healthy and temperatures_safe
    relay_present = sections["relay"][:1] == ["present"]
    can_text = "\n".join(sections["can"])
    can_healthy = (
        "can0" in can_text
        and "UP" in can_text
        and "ERROR-ACTIVE" in can_text
        and "bitrate 1000000" in can_text
    )
    camera_present = any("/dev/video" in line for line in sections["device_nodes"])
    failures: list[str] = []
    if not socket_present:
        failures.append("A1Z safe daemon socket /tmp/a1z.sock missing")
    elif not daemon_status:
        failures.append("A1Z safe daemon status missing")
    elif "probe_error" in daemon_status:
        failures.append(f"A1Z safe daemon status failed: {daemon_status['probe_error']}")
    else:
        if daemon_status.get("control_thread_alive") is not True:
            failures.append("A1Z safe daemon control thread is not healthy")
        if daemon_status.get("estopped") is not False:
            failures.append("A1Z safe daemon is emergency-stopped")
        if isinstance(error_codes, list) and any(
            not isinstance(code, (int, float)) or code < 0 or code > 1
            for code in error_codes
        ):
            failures.append(f"A1Z motor error codes are unsafe: {error_codes}")
        if not temperatures_valid:
            failures.append("A1Z motor temperatures are missing or invalid")
        else:
            assert hottest_mos is not None
            assert hottest_rotor is not None
            if hottest_mos >= MAX_MOTION_MOS_TEMP_C:
                failures.append(
                    f"A1Z MOS temperature {hottest_mos:.1f}C exceeds "
                    f"{MAX_MOTION_MOS_TEMP_C:.1f}C motion limit"
                )
            if hottest_rotor >= MAX_MOTION_ROTOR_TEMP_C:
                failures.append(
                    f"A1Z rotor temperature {hottest_rotor:.1f}C exceeds "
                    f"{MAX_MOTION_ROTOR_TEMP_C:.1f}C motion limit"
                )
    if not relay_present:
        failures.append("DGX policy relay 127.0.0.1:8765 missing")
    if not can_healthy:
        failures.append("CAN must be UP, ERROR-ACTIVE, and 1 Mbps")
    if not camera_present:
        failures.append("camera /dev/video* missing")
    return {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "healthy": daemon_healthy and relay_present and can_healthy and camera_present,
        "failures": failures,
        "a1z_socket": socket_present,
        "daemon_status": daemon_status,
        "policy_relay": relay_present,
        "can": sections["can"],
        "device_nodes": sections["device_nodes"],
        "device_details": sections["device_details"],
        "stable_links": sections["stable_links"],
        "usb_devices": sections["usb_devices"],
        "usbip": sections["usbip"],
    }


class SshMarkHardwareProbe:
    def __init__(self, *, host: str = "mark", timeout_s: float = 8.0) -> None:
        self._host = host
        self._timeout_s = timeout_s

    def snapshot(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    f"ConnectTimeout={max(1, int(self._timeout_s))}",
                    self._host,
                    REMOTE_PROBE_COMMAND,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self._failed_snapshot(str(exc))

        if result.returncode != 0:
            error = result.stderr.strip() or f"ssh exited with status {result.returncode}"
            return self._failed_snapshot(error)
        return parse_probe_output(result.stdout)

    def _failed_snapshot(self, error: str) -> dict[str, Any]:
        return {
            "probed_at": datetime.now(timezone.utc).isoformat(),
            "host": self._host,
            "healthy": False,
            "failures": [f"Mark SSH hardware probe failed: {error}"],
            "a1z_socket": False,
            "daemon_status": {},
            "policy_relay": False,
            "can": [],
            "device_nodes": [],
            "device_details": [],
            "stable_links": [],
            "usb_devices": [],
            "usbip": [],
            "error": error,
        }
