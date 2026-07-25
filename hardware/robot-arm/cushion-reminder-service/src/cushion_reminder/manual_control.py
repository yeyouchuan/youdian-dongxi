"""Small, allowlisted joint jog commands for the local hardware console."""

from __future__ import annotations

import json
import shlex
import subprocess
import threading
from typing import Protocol

CONTROLLED_JOINTS = {
    "j1": 0,
    "j2": 1,
    "j3": 2,
    "j5": 4,
    "j6": 5,
}
JOINT_LIMITS_DEGREES = (
    (-120.0, 120.0),
    (0.0, 180.0),
    (-180.0, 0.0),
    (-85.0, 85.0),
    (-85.0, 85.0),
    (-115.0, 115.0),
)
DEFAULT_JOG_DEGREES = 2.0
DEFAULT_GRIPPER_STEP = 0.1


class ManualControl(Protocol):
    mode: str

    def state(self) -> dict[str, object]: ...

    def jog(self, control: str, direction: int) -> dict[str, object]: ...

    def set_value(self, control: str, value: float) -> dict[str, object]: ...


def _validate_jog(control: str, direction: int) -> None:
    if control not in {*CONTROLLED_JOINTS, "gripper"}:
        raise ValueError(f"Unsupported manual control: {control}")
    if direction not in {-1, 1}:
        raise ValueError("direction must be -1 or 1")


def _validate_value(control: str, value: float) -> None:
    if control not in {*CONTROLLED_JOINTS, "gripper"}:
        raise ValueError(f"Unsupported manual control: {control}")
    if control == "gripper":
        if not 0.0 <= value <= 1.0:
            raise ValueError("gripper value must be in [0, 1]")
        return
    index = CONTROLLED_JOINTS[control]
    low, high = JOINT_LIMITS_DEGREES[index]
    if not low <= value <= high:
        raise ValueError(
            f"{control.upper()} target {value:g}° is outside [{low:g}, {high:g}]°"
        )


def _public_state(
    *, mode: str, joints_degrees: list[float], gripper: float
) -> dict[str, object]:
    return {
        "mode": mode,
        "joints_degrees": [round(value, 2) for value in joints_degrees],
        "gripper": round(gripper, 3),
        "controlled_joints": list(CONTROLLED_JOINTS),
        "joint_step_degrees": DEFAULT_JOG_DEGREES,
        "gripper_step": DEFAULT_GRIPPER_STEP,
    }


class ShadowManualControl:
    mode = "shadow"

    def __init__(self) -> None:
        self._joints = [0.0, 60.0, -60.0, 0.0, 0.0, 0.0]
        self._gripper = 1.0
        self._lock = threading.Lock()

    def state(self) -> dict[str, object]:
        with self._lock:
            return _public_state(
                mode=self.mode,
                joints_degrees=self._joints,
                gripper=self._gripper,
            )

    def jog(self, control: str, direction: int) -> dict[str, object]:
        _validate_jog(control, direction)
        with self._lock:
            if control == "gripper":
                self._gripper = min(
                    1.0,
                    max(0.0, self._gripper + direction * DEFAULT_GRIPPER_STEP),
                )
            else:
                index = CONTROLLED_JOINTS[control]
                low, high = JOINT_LIMITS_DEGREES[index]
                target = self._joints[index] + direction * DEFAULT_JOG_DEGREES
                if not low <= target <= high:
                    raise ValueError(
                        f"{control.upper()} target {target:g}° is outside [{low:g}, {high:g}]°"
                    )
                self._joints[index] = target
            return _public_state(
                mode=self.mode,
                joints_degrees=self._joints,
                gripper=self._gripper,
            )

    def set_value(self, control: str, value: float) -> dict[str, object]:
        _validate_value(control, value)
        with self._lock:
            if control == "gripper":
                self._gripper = value
            else:
                self._joints[CONTROLLED_JOINTS[control]] = value
            return _public_state(
                mode=self.mode,
                joints_degrees=self._joints,
                gripper=self._gripper,
            )


def _remote_python(action: str) -> str:
    """Build a fixed Python snippet; action is generated only from allowlisted values."""
    socket_helper = (
        "def q(c,a=None):\n"
        " s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);"
        "s.settimeout(30);s.connect('/tmp/a1z.sock');"
        "s.sendall((json.dumps({'cmd':c,'args':a or {}})+'\\n').encode());"
        "d=b''\n"
        " while b'\\n' not in d:\n"
        "  x=s.recv(4096)\n"
        "  if not x: break\n"
        "  d+=x\n"
        " s.close();r=json.loads(d.split(b'\\n',1)[0]);"
        "\n if not r.get('ok'): raise RuntimeError(r.get('error','A1Z command failed'))"
        "\n return r['data']\n"
    )
    source = f"import json,socket\n{socket_helper}{action}"
    return (
        "set -e; "
        "test -S /tmp/a1z.sock || "
        "{ echo 'A1Z safe daemon socket /tmp/a1z.sock is missing' >&2; exit 20; }; "
        '"$HOME/GALAXEA-A1Z/.venv/bin/python" -c '
        f"{shlex.quote(source)}"
    )


def build_mark_manual_state_command() -> str:
    return _remote_python(
        "st=q('status');print(json.dumps("
        "{'joints_degrees':st['pos_deg'],'gripper':st['gripper']}))"
    )


def build_mark_manual_jog_command(control: str, direction: int) -> str:
    _validate_jog(control, direction)
    if control == "gripper":
        delta = direction * DEFAULT_GRIPPER_STEP
        action = (
            "st=q('status');"
            f"g=min(1.0,max(0.0,float(st['gripper'])+({delta:g})));"
            "q('gripper',{'value':g});"
            "st=q('status');print(json.dumps("
            "{'joints_degrees':st['pos_deg'],'gripper':st['gripper']}))"
        )
    else:
        index = CONTROLLED_JOINTS[control]
        delta = direction * DEFAULT_JOG_DEGREES
        action = (
            "st=q('status');p=list(st['pos_deg']);"
            f"p[{index}]+=({delta:g});"
            "q('move',{'joints':p,'speed':0.1});"
            "st=q('status');print(json.dumps("
            "{'joints_degrees':st['pos_deg'],'gripper':st['gripper']}))"
        )
    return _remote_python(action)


def build_mark_manual_set_command(control: str, value: float) -> str:
    _validate_value(control, value)
    if control == "gripper":
        action = (
            f"q('gripper',{{'value':{value:g}}});"
            "st=q('status');print(json.dumps("
            "{'joints_degrees':st['pos_deg'],'gripper':st['gripper']}))"
        )
    else:
        index = CONTROLLED_JOINTS[control]
        action = (
            "st=q('status');p=list(st['pos_deg']);"
            f"p[{index}]={value:g};"
            "q('move',{'joints':p,'speed':0.1});"
            "st=q('status');print(json.dumps("
            "{'joints_degrees':st['pos_deg'],'gripper':st['gripper']}))"
        )
    return _remote_python(action)


class SshMarkManualControl:
    mode = "ssh-mark"

    def __init__(self, *, host: str = "mark", timeout_s: float = 35.0) -> None:
        self._host = host
        self._timeout_s = timeout_s
        self._lock = threading.Lock()

    def _run(self, command: str) -> dict[str, object]:
        try:
            result = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", self._host, command],
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"Mark manual-control command exceeded {self._timeout_s:.0f}s"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(detail or f"Mark command exited with status {result.returncode}")
        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
            joints = [float(value) for value in data["joints_degrees"]]
            gripper = float(data["gripper"])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Mark returned an invalid manual-control response") from exc
        if len(joints) != 6 or not 0.0 <= gripper <= 1.0:
            raise RuntimeError("Mark returned an invalid joint or gripper state")
        return _public_state(mode=self.mode, joints_degrees=joints, gripper=gripper)

    def state(self) -> dict[str, object]:
        with self._lock:
            return self._run(build_mark_manual_state_command())

    def jog(self, control: str, direction: int) -> dict[str, object]:
        with self._lock:
            return self._run(build_mark_manual_jog_command(control, direction))

    def set_value(self, control: str, value: float) -> dict[str, object]:
        with self._lock:
            return self._run(build_mark_manual_set_command(control, value))
