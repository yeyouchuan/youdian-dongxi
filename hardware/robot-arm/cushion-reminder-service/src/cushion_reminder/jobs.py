"""In-memory scenario workflow and append-only log for the local console."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .execution import (
    NEUTRAL_POSE_DEGREES,
    ZERO_POSE_DEGREES,
    NeutralPoseExecutor,
    RobotExecutor,
)
from .hardware import HardwareProbe
from .manipulation_workflow import ManipulationWorkflow
from .scenarios import Scenario


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    id: str
    scenario_id: str
    status: str = "queued"
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    completed_at: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("events")
        data["event_count"] = len(self.events)
        return data


def simulated_seated_threshold_event(*, now: datetime | None = None) -> dict[str, Any]:
    observed_at = now or utc_now()
    return {
        "schema_version": 1,
        "device_id": "cushion-simulator-001",
        "topic": "zuodian/posture",
        "pose": "UPRIGHT",
        "session_started_at": (observed_at - timedelta(hours=1)).isoformat(),
        "observed_at": observed_at.isoformat(),
        "effective_seated_seconds": 3600,
        "reason": "continuous_seated_60m",
        "simulated": True,
    }


class JobManager:
    def __init__(
        self,
        executor: RobotExecutor,
        neutral_executor: NeutralPoseExecutor,
        *,
        exterior_camera_ready: bool = False,
        mounted_as_exterior_ready: bool = False,
        hardware_probe: HardwareProbe | None = None,
        camera_readiness: Callable[[], bool] | None = None,
        manipulation_workflow: ManipulationWorkflow | None = None,
    ) -> None:
        self.executor = executor
        self.neutral_executor = neutral_executor
        self._exterior_camera_ready = exterior_camera_ready
        self._camera_readiness = camera_readiness
        self.mounted_as_exterior_ready = mounted_as_exterior_ready
        self.hardware_probe = hardware_probe
        self.manipulation_workflow = manipulation_workflow
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._active_job_id: str | None = None

    @property
    def mode(self) -> str:
        return self.executor.mode

    @property
    def exterior_camera_ready(self) -> bool:
        return self._exterior_camera_ready or bool(
            self._camera_readiness is not None and self._camera_readiness()
        )

    def trigger(
        self,
        scenario: Scenario,
        *,
        trigger_event: dict[str, object] | None = None,
    ) -> Job:
        with self._lock:
            if self._active_job_id is not None:
                active = self._jobs[self._active_job_id]
                if active.status in {"queued", "running"}:
                    raise RuntimeError(f"Robot job {active.id} is already active")
            job = Job(id=uuid.uuid4().hex, scenario_id=scenario.id)
            self._jobs[job.id] = job
            self._active_job_id = job.id
            self._append_locked(
                job,
                "info",
                "[1/6] Scenario accepted",
                {"scenario_id": scenario.id, "execution_mode": self.mode},
            )
        thread = threading.Thread(
            target=self._run,
            args=(job.id, scenario, trigger_event),
            name=f"scenario-{job.id[:8]}",
            daemon=True,
        )
        thread.start()
        return job

    def trigger_return_neutral(self) -> Job:
        with self._lock:
            self._ensure_idle_locked()
            job = Job(id=uuid.uuid4().hex, scenario_id="return_neutral")
            self._jobs[job.id] = job
            self._active_job_id = job.id
            self._append_locked(
                job,
                "info",
                "[1/4] Deterministic return-neutral command accepted",
                {"execution_mode": self.mode},
            )
        thread = threading.Thread(
            target=self._run_return_neutral,
            args=(job.id,),
            name=f"return-neutral-{job.id[:8]}",
            daemon=True,
        )
        thread.start()
        return job

    def trigger_return_zero(self) -> Job:
        with self._lock:
            self._ensure_idle_locked()
            job = Job(id=uuid.uuid4().hex, scenario_id="return_zero")
            self._jobs[job.id] = job
            self._active_job_id = job.id
            self._append_locked(
                job,
                "info",
                "[1/4] Deterministic J3 cooldown zero-pose command accepted",
                {"execution_mode": self.mode},
            )
        thread = threading.Thread(
            target=self._run_return_zero,
            args=(job.id,),
            name=f"return-zero-{job.id[:8]}",
            daemon=True,
        )
        thread.start()
        return job

    def ensure_idle(self) -> None:
        """Reject direct controls while a scenario or neutral-pose job is active."""
        with self._lock:
            self._ensure_idle_locked()

    def get(self, job_id: str) -> Job:
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError as exc:
                raise KeyError(f"Unknown job: {job_id}") from exc

    def events_after(self, job_id: str, after: int) -> list[dict[str, Any]]:
        with self._lock:
            job = self.get_unlocked(job_id)
            return [dict(event) for event in job.events if event["sequence"] > after]

    def _run(
        self,
        job_id: str,
        scenario: Scenario,
        trigger_event: dict[str, object] | None,
    ) -> None:
        job = self.get(job_id)
        self._set_status(job, "running")
        try:
            if trigger_event is not None:
                self._append(
                    job,
                    "event",
                    "[2/6] Received MQTT continuous-sitting threshold event",
                    trigger_event,
                )
            elif scenario.trigger_kind == "continuous_seated_60m":
                cushion_event = simulated_seated_threshold_event()
                self._append(
                    job,
                    "event",
                    "[2/6] Received simulated continuous-sitting threshold event",
                    cushion_event,
                )
            else:
                self._append(
                    job,
                    "event",
                    "[2/6] Received manual test scenario trigger",
                    {"scenario_id": scenario.id, "simulated": True},
                )
            self._append(
                job,
                "info",
                "[3/6] Created allowlisted RobotIntent",
                {
                    "intent_type": scenario.intent_type,
                    "prompt": scenario.prompt,
                    "max_steps": scenario.max_steps,
                    "camera_profile": scenario.camera_profile.id,
                    "mark_config_name": scenario.camera_profile.mark_config_name,
                },
            )
            if scenario.camera_profile.requires_physical_exterior:
                self._append(
                    job,
                    "warning",
                    "Scenario requires a real exterior camera before live execution",
                    None,
                )
                if self.mode != "shadow" and not self.exterior_camera_ready:
                    raise RuntimeError(
                        "Live execution blocked: exterior camera readiness was not confirmed"
                    )
            if (
                scenario.camera_profile.requires_diagnostic_opt_in
                and self.mode != "shadow"
                and not self.mounted_as_exterior_ready
            ):
                raise RuntimeError(
                    "Live execution blocked: mounted-as-exterior diagnostic mode "
                    "requires explicit opt-in"
                )

            self._append(
                job,
                "info",
                "[4/6] Starting Mark hardware preflight",
                {"camera_profile": scenario.camera_profile.id},
            )
            if self.hardware_probe is not None:
                hardware = self.hardware_probe.snapshot()
                self._append(job, "hardware", "[4/6] Mark hardware snapshot", hardware)
                if self.mode != "shadow" and not hardware.get("healthy", False):
                    failures = hardware.get("failures", [])
                    details = (
                        "; ".join(str(failure) for failure in failures)
                        if failures
                        else "unknown hardware gate"
                    )
                    raise RuntimeError(
                        f"Live execution blocked: Mark hardware preflight failed: {details}"
                    )
                device_details = "\n".join(hardware.get("device_details", []))
                required_vid_pid = scenario.camera_profile.required_vid_pid
                if self.mode != "shadow" and required_vid_pid not in device_details:
                    raise RuntimeError(
                        "Live execution blocked: camera profile device identity mismatch"
                    )
            log = lambda level, message, data: self._append(job, level, message, data)
            if scenario.intent_type == "grasp_test_object" and self.mode != "shadow":
                if self.manipulation_workflow is None:
                    raise RuntimeError(
                        "Live grasp blocked: two-view GPT-5.6 evaluation is not configured"
                    )
                result = self.manipulation_workflow.run(scenario, log)
            else:
                result = self.executor.execute(scenario, log)
            self._append(job, "info", "[6/6] Scenario workflow completed", asdict(result))
            self._set_status(job, "succeeded")
        except Exception as exc:  # noqa: BLE001 - job boundary must persist adapter failures
            self._append(job, "error", str(exc), {"error_type": type(exc).__name__})
            self._set_status(job, "failed")
        finally:
            with self._lock:
                if self._active_job_id == job.id:
                    self._active_job_id = None

    def _run_return_neutral(self, job_id: str) -> None:
        job = self.get(job_id)
        self._set_status(job, "running")
        try:
            self._append(
                job,
                "info",
                "[2/4] Starting Mark neutral-pose hardware preflight",
                {"target_degrees": list(NEUTRAL_POSE_DEGREES)},
            )
            if self.hardware_probe is not None:
                hardware = self.hardware_probe.snapshot()
                self._append(job, "hardware", "[2/4] Mark hardware snapshot", hardware)
                can_text = "\n".join(hardware.get("can", []))
                neutral_hardware_healthy = (
                    hardware.get("a1z_socket", False)
                    and "UP" in can_text
                    and "ERROR-ACTIVE" in can_text
                    and "bitrate 1000000" in can_text
                )
                if self.mode != "shadow" and not neutral_hardware_healthy:
                    raise RuntimeError(
                        "Live return-neutral blocked: safe daemon or CAN preflight failed"
                    )
            result = self.neutral_executor.return_neutral(
                lambda level, message, data: self._append(job, level, message, data)
            )
            self._append(job, "info", "[4/4] Neutral pose workflow completed", asdict(result))
            self._set_status(job, "succeeded")
        except Exception as exc:  # noqa: BLE001 - job boundary must persist adapter failures
            self._append(job, "error", str(exc), {"error_type": type(exc).__name__})
            self._set_status(job, "failed")
        finally:
            with self._lock:
                if self._active_job_id == job.id:
                    self._active_job_id = None

    def _run_return_zero(self, job_id: str) -> None:
        job = self.get(job_id)
        self._set_status(job, "running")
        try:
            self._append(
                job,
                "info",
                "[2/4] Starting Mark J3 cooldown zero-pose hardware preflight",
                {"target_degrees": list(ZERO_POSE_DEGREES)},
            )
            if self.hardware_probe is not None:
                hardware = self.hardware_probe.snapshot()
                self._append(job, "hardware", "[2/4] Mark hardware snapshot", hardware)
                can_text = "\n".join(hardware.get("can", []))
                zero_pose_hardware_healthy = (
                    hardware.get("a1z_socket", False)
                    and "UP" in can_text
                    and "ERROR-ACTIVE" in can_text
                    and "bitrate 1000000" in can_text
                )
                if self.mode != "shadow" and not zero_pose_hardware_healthy:
                    raise RuntimeError(
                        "Live return-zero blocked: safe daemon or CAN preflight failed"
                    )
            result = self.neutral_executor.return_zero(
                lambda level, message, data: self._append(job, level, message, data)
            )
            self._append(job, "info", "[4/4] J3 cooldown zero-pose workflow completed", asdict(result))
            self._set_status(job, "succeeded")
        except Exception as exc:  # noqa: BLE001 - job boundary must persist adapter failures
            self._append(job, "error", str(exc), {"error_type": type(exc).__name__})
            self._set_status(job, "failed")
        finally:
            with self._lock:
                if self._active_job_id == job.id:
                    self._active_job_id = None

    def _ensure_idle_locked(self) -> None:
        if self._active_job_id is not None:
            active = self._jobs[self._active_job_id]
            if active.status in {"queued", "running"}:
                raise RuntimeError(f"Robot job {active.id} is already active")

    def _set_status(self, job: Job, status: str) -> None:
        with self._lock:
            job.status = status
            if status in {"succeeded", "failed"}:
                job.completed_at = utc_now().isoformat()

    def _append(
        self,
        job: Job,
        level: str,
        message: str,
        data: dict[str, object] | None,
    ) -> None:
        with self._lock:
            self._append_locked(job, level, message, data)

    def _append_locked(
        self,
        job: Job,
        level: str,
        message: str,
        data: dict[str, object] | None,
    ) -> None:
        job.events.append(
            {
                "sequence": len(job.events) + 1,
                "at": utc_now().isoformat(),
                "level": level,
                "message": message,
                "data": data,
            }
        )

    def get_unlocked(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"Unknown job: {job_id}") from exc
