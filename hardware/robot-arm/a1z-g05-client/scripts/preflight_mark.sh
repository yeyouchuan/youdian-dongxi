#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--operator-checked" ]]; then
  echo "Usage: $0 --operator-checked" >&2
  echo "Use the flag only after physically checking free joint motion, binding," >&2
  echo "cable strain, abnormal sound, base security, and the clear workspace." >&2
  exit 2
fi

echo "Host: $(hostname)"
echo "Checking camera..."
if ! compgen -G "/dev/video*" >/dev/null; then
  echo "FAIL: no /dev/video* device is visible in mark/WSL." >&2
  exit 1
fi
ls -l /dev/video*

echo "Checking SocketCAN..."
if ! ip link show can0 >/dev/null 2>&1; then
  echo "FAIL: can0 is not visible. Attach the USB-CAN adapter to WSL and configure SocketCAN." >&2
  exit 1
fi
ip -details link show can0

echo "Checking official A1Z daemon socket..."
if [[ ! -S /tmp/a1z.sock ]]; then
  echo "FAIL: /tmp/a1z.sock is absent." >&2
  echo "Start the pinned official SDK server with gripper support before the client." >&2
  exit 1
fi

for model in \
  "$HOME/.cache/a1z-g05/so101_new_calib.urdf" \
  "$HOME/GALAXEA-A1Z/a1z/robot_models/a1z/A1Z_G1Z.urdf"; do
  if [[ ! -f "$model" ]]; then
    echo "FAIL: kinematic model is missing: $model" >&2
    echo "Run scripts/setup_mark_kinematics.sh first." >&2
    exit 1
  fi
done

echo "Checking live A1Z feedback, temperatures, and motor errors..."
python3 - <<'PY'
import json
import socket

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.settimeout(2.0)
    sock.connect("/tmp/a1z.sock")
    sock.sendall(b'{"cmd":"status","args":{}}\n')
    payload = bytearray()
    while b"\n" not in payload:
        chunk = sock.recv(4096)
        if not chunk:
            break
        payload.extend(chunk)

response = json.loads(bytes(payload).split(b"\n", 1)[0])
if not response.get("ok"):
    raise SystemExit(f"FAIL: A1Z status RPC failed: {response.get('error')}")
data = response["data"]
required = ("pos_deg", "vel_rad_s", "temp_mos_c", "temp_rotor_c", "error_codes", "gripper")
missing = [key for key in required if data.get(key) is None]
if missing:
    raise SystemExit(f"FAIL: A1Z status missing required telemetry: {missing}")
if len(data["pos_deg"]) != 6 or len(data["vel_rad_s"]) != 6:
    raise SystemExit("FAIL: A1Z joint feedback does not contain six axes")
# The official drivers report 0x0 while disabled and 0x1 while enabled/normal.
# Codes 0x8 and above represent actual voltage/current/thermal/comms faults.
bad_codes = [int(code) for code in data["error_codes"] if int(code) not in (0x0, 0x1)]
if bad_codes:
    raise SystemExit(f"FAIL: motor fault codes are present: {data['error_codes']}")
if max(data["temp_mos_c"]) >= 70 or max(data["temp_rotor_c"]) >= 90:
    raise SystemExit(
        "FAIL: motor temperature is above conservative preflight threshold: "
        f"MOS={data['temp_mos_c']}, rotor={data['temp_rotor_c']}"
    )
print(
    "A1Z feedback OK:",
    f"joints={data['pos_deg']}",
    f"gripper={data['gripper']}",
    f"MOS max={max(data['temp_mos_c'])}C",
    f"rotor max={max(data['temp_rotor_c'])}C",
)
PY

echo "Checking DGX policy relay..."
if ! timeout 2 bash -c "</dev/tcp/127.0.0.1/8765"; then
  echo "FAIL: localhost:8765 is not reachable. Start relay_policy_to_mark.sh on the Mac." >&2
  exit 1
fi

echo "PASS: operator checks, live telemetry, devices, daemon, and relay passed."
echo "No motion command was sent."
