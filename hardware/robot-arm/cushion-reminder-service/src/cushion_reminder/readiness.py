"""Combined MQTT and Mark readiness for unattended demo checks."""

from __future__ import annotations

from typing import Protocol


class StatusSource(Protocol):
    def status(self) -> dict[str, object]: ...


class SnapshotSource(Protocol):
    def snapshot(self) -> dict[str, object]: ...


def build_readiness(
    mqtt: StatusSource,
    hardware: SnapshotSource,
    *,
    execution_mode: str | None = None,
    mounted_as_exterior_ready: bool | None = None,
) -> dict[str, object]:
    mqtt_status = mqtt.status()
    hardware_status = hardware.snapshot()
    blockers: list[str] = []

    if not mqtt_status.get("connected", False):
        blockers.append("MQTT subscriber is disconnected")

    if not hardware_status.get("healthy", False):
        failures = hardware_status.get("failures", [])
        if isinstance(failures, list) and failures:
            blockers.extend(str(failure) for failure in failures)
        else:
            blockers.append("Mark hardware preflight is unhealthy")
    if execution_mode is not None and execution_mode != "ssh-mark":
        blockers.append("service execution mode is not ssh-mark")
    if mounted_as_exterior_ready is not None and not mounted_as_exterior_ready:
        blockers.append("mounted-as-exterior camera mode is not enabled")

    return {
        "ready": not blockers,
        "blockers": blockers,
        "mqtt": mqtt_status,
        "hardware": hardware_status,
    }
