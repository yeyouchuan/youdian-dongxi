"""Safe execution adapters for scenario jobs."""

from __future__ import annotations

import re
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePath
from queue import Empty, Queue
from typing import Protocol

from .scenarios import Scenario

LogCallback = Callable[[str, str, dict[str, object] | None], None]
_HEADLESS_STEP = re.compile(
    r"^step=(?P<step>\d+)\s+hz=(?P<hz>\d+(?:\.\d+)?)\s+"
    r"need_obs=(?P<need_obs>True|False)\s+error=(?P<error>.*)$"
)
NEUTRAL_POSE_DEGREES = (0.0, 60.0, -60.0, 0.0, 0.0, 0.0)
ZERO_POSE_DEGREES = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
NEUTRAL_POSE_SPEED = 0.15


def parse_headless_step(line: str) -> dict[str, object] | None:
    match = _HEADLESS_STEP.match(line.strip())
    if match is None:
        return None
    error = match.group("error")
    return {
        "step": int(match.group("step")),
        "hz": float(match.group("hz")),
        "need_observation": match.group("need_obs") == "True",
        "error": None if error == "-" else error,
    }


@dataclass(frozen=True)
class ExecutionResult:
    steps_requested: int
    mode: str


class RobotExecutor(Protocol):
    mode: str

    def execute(self, scenario: Scenario, log: LogCallback) -> ExecutionResult: ...


class NeutralPoseExecutor(Protocol):
    mode: str

    def return_neutral(self, log: LogCallback) -> ExecutionResult: ...

    def return_zero(self, log: LogCallback) -> ExecutionResult: ...


class ShadowRobotExecutor:
    mode = "shadow"

    def execute(self, scenario: Scenario, log: LogCallback) -> ExecutionResult:
        log(
            "info",
            "Shadow mode: DGX request and A1Z motion were not sent",
            {"prompt": scenario.prompt, "max_steps": scenario.max_steps},
        )
        time.sleep(0.1)
        return ExecutionResult(steps_requested=scenario.max_steps, mode=self.mode)


class ShadowNeutralPoseExecutor:
    mode = "shadow"

    def return_neutral(self, log: LogCallback) -> ExecutionResult:
        log(
            "info",
            "Shadow mode: deterministic neutral pose was not sent",
            {
                "target_degrees": list(NEUTRAL_POSE_DEGREES),
                "speed": NEUTRAL_POSE_SPEED,
            },
        )
        return ExecutionResult(steps_requested=1, mode=self.mode)

    def return_zero(self, log: LogCallback) -> ExecutionResult:
        log(
            "info",
            "Shadow mode: deterministic J3 cooldown zero pose was not sent",
            {
                "target_degrees": list(ZERO_POSE_DEGREES),
                "speed": NEUTRAL_POSE_SPEED,
            },
        )
        return ExecutionResult(steps_requested=1, mode=self.mode)


def _build_mark_fixed_pose_command(
    target_degrees: tuple[float, ...],
    *,
    remote_timeout_s: int,
) -> str:
    if remote_timeout_s <= 0:
        raise ValueError("Remote timeout must be greater than zero")
    target = ",".join(f"{angle:g}" for angle in target_degrees)
    return (
        "set -e; "
        "test -S /tmp/a1z.sock || "
        "{ echo 'A1Z safe daemon socket /tmp/a1z.sock is missing' >&2; exit 20; }; "
        f"timeout --signal=TERM --kill-after=5s {remote_timeout_s}s "
        '"$HOME/GALAXEA-A1Z/.venv/bin/python" '
        '"$HOME/GALAXEA-A1Z/tools/a1zctl" '
        f"move {target} --speed {NEUTRAL_POSE_SPEED:g}"
    )


def build_mark_return_neutral_command(*, remote_timeout_s: int = 55) -> str:
    """Build the fixed, deterministic A1Z neutral-pose command."""
    return _build_mark_fixed_pose_command(
        NEUTRAL_POSE_DEGREES,
        remote_timeout_s=remote_timeout_s,
    )


def build_mark_return_zero_command(*, remote_timeout_s: int = 55) -> str:
    """Build the fixed five-controlled-joint zero-pose command."""
    return _build_mark_fixed_pose_command(
        ZERO_POSE_DEGREES,
        remote_timeout_s=remote_timeout_s,
    )


class SshMarkNeutralPoseExecutor:
    mode = "ssh-mark"

    def __init__(self, *, host: str = "mark", timeout_s: float = 60.0) -> None:
        self._host = host
        self._timeout_s = timeout_s

    def return_neutral(self, log: LogCallback) -> ExecutionResult:
        remote_command = build_mark_return_neutral_command(
            remote_timeout_s=max(1, int(self._timeout_s - 5))
        )
        log(
            "info",
            "[3/4] Dispatching fixed neutral pose to Mark",
            {
                "host": self._host,
                "target_degrees": list(NEUTRAL_POSE_DEGREES),
                "speed": NEUTRAL_POSE_SPEED,
            },
        )
        try:
            result = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", self._host, remote_command],
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"Mark neutral-pose command exceeded {self._timeout_s:.0f}s"
            ) from exc
        for line in (result.stdout + result.stderr).splitlines():
            log("robot", line, None)
        if result.returncode != 0:
            raise RuntimeError(f"Mark neutral-pose command exited with status {result.returncode}")
        return ExecutionResult(steps_requested=1, mode=self.mode)

    def return_zero(self, log: LogCallback) -> ExecutionResult:
        remote_command = build_mark_return_zero_command(
            remote_timeout_s=max(1, int(self._timeout_s - 5))
        )
        log(
            "info",
            "[3/4] Dispatching fixed J3 cooldown zero pose to Mark",
            {
                "host": self._host,
                "target_degrees": list(ZERO_POSE_DEGREES),
                "speed": NEUTRAL_POSE_SPEED,
            },
        )
        try:
            result = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", self._host, remote_command],
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"Mark zero-pose command exceeded {self._timeout_s:.0f}s"
            ) from exc
        for line in (result.stdout + result.stderr).splitlines():
            log("robot", line, None)
        if result.returncode != 0:
            raise RuntimeError(f"Mark zero-pose command exited with status {result.returncode}")
        return ExecutionResult(steps_requested=1, mode=self.mode)


def build_mark_remote_command(
    scenario: Scenario,
    *,
    config_name: str | None = None,
    remote_timeout_s: int = 175,
) -> str:
    """Build a fixed-catalog robot command; no API-supplied text enters the shell."""
    selected_config = config_name or scenario.camera_profile.mark_config_name
    if PurePath(selected_config).name != selected_config or not selected_config.endswith(".yaml"):
        raise ValueError("Mark config must be a YAML filename without a path")
    if remote_timeout_s <= 0:
        raise ValueError("Remote timeout must be greater than zero")
    arguments = [
        "-m",
        "a1z_g05.headless",
        "--config",
        selected_config,
        "--task",
        scenario.prompt,
        "--max-steps",
        str(scenario.max_steps),
    ]
    quoted_arguments = " ".join(shlex.quote(part) for part in arguments)
    return (
        "set -e; "
        "test -S /tmp/a1z.sock || "
        "{ echo 'A1Z safe daemon socket /tmp/a1z.sock is missing' >&2; exit 20; }; "
        "cd ~/hardware/robot-arm/a1z-g05-client; "
        f"test -f {shlex.quote(selected_config)} || "
        "{ echo 'Mark G0.5 config is missing' >&2; exit 21; }; "
        'python_path="$HOME/GALAXEA-A1Z/.venv/bin/python"; '
        f"timeout --signal=TERM --kill-after=5s {remote_timeout_s}s "
        f'env PYTHONPATH=. PYTHONUNBUFFERED=1 "$python_path" {quoted_arguments}'
    )


class SshMarkRobotExecutor:
    mode = "ssh-mark"

    def __init__(
        self,
        *,
        host: str = "mark",
        timeout_s: float = 360.0,
        config_name: str | None = None,
    ) -> None:
        self._host = host
        self._timeout_s = timeout_s
        self._config_name = config_name

    def execute(self, scenario: Scenario, log: LogCallback) -> ExecutionResult:
        remote_command = build_mark_remote_command(
            scenario,
            config_name=self._config_name or scenario.camera_profile.mark_config_name,
            remote_timeout_s=max(1, int(self._timeout_s - 5)),
        )
        log(
            "info",
            "[5/6] Dispatching to Mark; Mark is requesting action chunks from DGX",
            {"host": self._host, "max_steps": scenario.max_steps},
        )
        process = subprocess.Popen(
            ["ssh", "-o", "BatchMode=yes", self._host, remote_command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        lines: Queue[str | None] = Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line.rstrip())
            lines.put(None)

        reader = threading.Thread(target=read_output, name="mark-output-reader", daemon=True)
        reader.start()
        last_step_state: tuple[object, object, object] | None = None
        try:
            deadline = time.monotonic() + self._timeout_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.terminate()
                    raise TimeoutError(f"Mark execution exceeded {self._timeout_s:.0f}s")
                try:
                    line = lines.get(timeout=min(0.2, remaining))
                except Empty:
                    continue
                if line is None:
                    break
                step = parse_headless_step(line)
                if step is None:
                    log("robot", line, None)
                else:
                    step_state = (
                        step["step"],
                        step["need_observation"],
                        step["error"],
                    )
                    if step_state != last_step_state:
                        log("action", f"A1Z action step {step['step']}", step)
                        last_step_state = step_state
            return_code = process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.terminate()

        if return_code != 0:
            raise RuntimeError(f"Mark robot command exited with status {return_code}")
        return ExecutionResult(steps_requested=scenario.max_steps, mode=self.mode)
