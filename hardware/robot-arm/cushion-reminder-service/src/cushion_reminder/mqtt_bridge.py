"""MQTT receiver and continuous-sitting trigger state."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .simulator import POSTURE_TOPIC, RADAR_TOPIC

OCCUPIED_POSES = frozenset({"UPRIGHT", "LEAN_L", "LEAN_R", "EDGE", "OTHER"})
TEST_EVENT_KINDS = frozenset({"occupied", "continuous-seated", "away", "radar"})


class MqttBridge(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def status(self) -> dict[str, object]: ...

    def events_after(self, after: int) -> list[dict[str, object]]: ...

    def publish_test_event(self, kind: str) -> dict[str, object]: ...


@dataclass(frozen=True)
class PostureDecision:
    pose: str
    occupied: bool
    seated_seconds: float
    threshold_seconds: float
    threshold_reached: bool
    new_trigger: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class SeatedStateTracker:
    """Convert posture samples into one trigger per continuous occupied session."""

    def __init__(self, *, threshold_seconds: float) -> None:
        if threshold_seconds <= 0:
            raise ValueError("threshold_seconds must be greater than zero")
        self.threshold_seconds = float(threshold_seconds)
        self._seated_since: float | None = None
        self._triggered = False

    def ingest(self, payload: dict[str, Any], *, now: float) -> PostureDecision:
        pose_value = payload.get("pose")
        if not isinstance(pose_value, str):
            raise TypeError("posture payload requires a string pose")
        pose = pose_value.strip().upper()
        if pose != "AWAY" and pose not in OCCUPIED_POSES:
            raise ValueError(f"unsupported posture pose: {pose!r}")

        occupied = pose in OCCUPIED_POSES
        if not occupied:
            self._seated_since = None
            self._triggered = False
            return self._decision(pose=pose, occupied=False, seated_seconds=0.0)

        if self._seated_since is None:
            self._seated_since = now

        if payload.get("simulated") is True:
            simulated_seconds = payload.get("effective_seated_seconds")
            if isinstance(simulated_seconds, (int, float)) and simulated_seconds >= 0:
                self._seated_since = min(self._seated_since, now - float(simulated_seconds))

        seated_seconds = max(0.0, now - self._seated_since)
        return self._decision(pose=pose, occupied=True, seated_seconds=seated_seconds)

    def allow_trigger_retry(self) -> None:
        """Allow a failed downstream job submission to retry in the same session."""
        if self._seated_since is not None:
            self._triggered = False

    def _decision(
        self,
        *,
        pose: str,
        occupied: bool,
        seated_seconds: float,
    ) -> PostureDecision:
        threshold_reached = occupied and seated_seconds >= self.threshold_seconds
        new_trigger = threshold_reached and not self._triggered
        if new_trigger:
            self._triggered = True
        return PostureDecision(
            pose=pose,
            occupied=occupied,
            seated_seconds=round(seated_seconds, 3),
            threshold_seconds=self.threshold_seconds,
            threshold_reached=threshold_reached,
            new_trigger=new_trigger,
        )


class CushionMqttBridge:
    """Subscribe to cushion topics and publish allowlisted test packets."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        transport: str = "tcp",
        threshold_seconds: float,
        on_threshold: Callable[[PostureDecision], object],
        client_id: str = "a1z-cushion-receiver",
    ) -> None:
        if transport not in {"tcp", "websockets"}:
            raise ValueError("MQTT transport must be 'tcp' or 'websockets'")
        self.host = host
        self.port = port
        self.transport = transport
        self.client_id = client_id
        self._on_threshold = on_threshold
        self._tracker = SeatedStateTracker(threshold_seconds=threshold_seconds)
        self._client: Any | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._events: deque[dict[str, object]] = deque(maxlen=500)
        self._sequence = 0
        self._last_posture: dict[str, Any] | None = None
        self._last_radar: dict[str, Any] | None = None
        self._last_decision: PostureDecision | None = None
        self._trigger_retry_after = 0.0

    def start(self) -> None:
        if self._client is not None:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required for the MQTT receiver") from exc

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            transport=self.transport,
        )

        def on_connect(
            connected_client: Any,
            userdata: Any,
            flags: Any,
            reason_code: Any,
            properties: Any,
        ) -> None:
            del userdata, flags, properties
            if reason_code == 0:
                connected_client.subscribe("zuodian/#", qos=0)
                with self._lock:
                    self._connected = True
                self._append("info", "MQTT subscriber connected", {"topic": "zuodian/#"})
            else:
                self._append(
                    "error",
                    "MQTT subscriber connection rejected",
                    {"reason_code": str(reason_code)},
                )

        def on_disconnect(
            disconnected_client: Any,
            userdata: Any,
            disconnect_flags: Any,
            reason_code: Any,
            properties: Any,
        ) -> None:
            del disconnected_client, userdata, disconnect_flags, properties
            with self._lock:
                self._connected = False
            self._append(
                "warning",
                "MQTT subscriber disconnected; reconnecting",
                {"reason_code": str(reason_code)},
            )

        def on_message(client_: Any, userdata: Any, message: Any) -> None:
            del client_, userdata
            self.ingest_message(message.topic, message.payload)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=15)
        self._client = client
        self._append(
            "info",
            "Starting MQTT subscriber",
            {
                "host": self.host,
                "port": self.port,
                "transport": self.transport,
                "topic": "zuodian/#",
            },
        )
        client.connect_async(self.host, self.port, keepalive=30)
        client.loop_start()

    def stop(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        client.disconnect()
        client.loop_stop()
        with self._lock:
            self._connected = False

    def ingest_message(
        self,
        topic: str,
        raw_payload: bytes | str,
        *,
        now: float | None = None,
    ) -> None:
        try:
            decoded = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            payload = json.loads(decoded)
            if not isinstance(payload, dict):
                raise TypeError("MQTT JSON payload must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            self._append(
                "error",
                "Invalid MQTT payload ignored",
                {"topic": topic, "error": str(exc)},
            )
            return

        if topic == POSTURE_TOPIC:
            self._ingest_posture(payload, now=time.monotonic() if now is None else now)
        elif topic == RADAR_TOPIC:
            with self._lock:
                self._last_radar = dict(payload)
            self._append("mqtt", "MQTT radar received", {"topic": topic, **payload})
        else:
            self._append("mqtt", "MQTT topic received", {"topic": topic, **payload})

    def publish_test_event(self, kind: str) -> dict[str, object]:
        topic, payload = self.test_event(kind)
        client = self._client
        with self._lock:
            connected = self._connected
        if client is None or not connected:
            raise RuntimeError(f"MQTT broker {self.host}:{self.port} is not connected")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        info = client.publish(topic, encoded, qos=0, retain=False)
        if info.rc != 0:
            raise RuntimeError(f"MQTT publish failed for {topic}: rc={info.rc}")
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            raise TimeoutError(f"MQTT publish timed out for {topic}")
        self._append("test", "MQTT test event published", {"topic": topic, **payload})
        return {"topic": topic, "payload": payload}

    def test_event(self, kind: str) -> tuple[str, dict[str, object]]:
        if kind not in TEST_EVENT_KINDS:
            raise KeyError(f"Unknown MQTT test event: {kind}")
        if kind == "radar":
            return RADAR_TOPIC, {
                "heart": 82.0,
                "heart_med": 82.0,
                "breath": 16.0,
                "breath_med": 16.0,
                "dist": 75.0,
                "seq": int(time.time()),
                "simulated": True,
            }
        payload: dict[str, object] = {
            "s1": 220 if kind != "away" else 1,
            "s3": 90 if kind != "away" else 1,
            "s4": 210 if kind != "away" else 1,
            "s5": 135 if kind != "away" else 1,
            "s6": 130 if kind != "away" else 1,
            "pose": "AWAY" if kind == "away" else "UPRIGHT",
            "simulated": True,
        }
        if kind == "continuous-seated":
            payload["effective_seated_seconds"] = self._tracker.threshold_seconds
        return POSTURE_TOPIC, payload

    def status(self) -> dict[str, object]:
        with self._lock:
            decision = self._last_decision
            return {
                "host": self.host,
                "port": self.port,
                "transport": self.transport,
                "connected": self._connected,
                "topic_filter": "zuodian/#",
                "threshold_seconds": self._tracker.threshold_seconds,
                "pose": decision.pose if decision else None,
                "occupied": decision.occupied if decision else False,
                "seated_seconds": decision.seated_seconds if decision else 0.0,
                "threshold_reached": decision.threshold_reached if decision else False,
                "last_posture": dict(self._last_posture) if self._last_posture else None,
                "last_radar": dict(self._last_radar) if self._last_radar else None,
                "event_count": self._sequence,
            }

    def events_after(self, after: int) -> list[dict[str, object]]:
        with self._lock:
            return [dict(event) for event in self._events if int(event["sequence"]) > after]

    def _ingest_posture(self, payload: dict[str, Any], *, now: float) -> None:
        try:
            decision = self._tracker.ingest(payload, now=now)
        except (TypeError, ValueError) as exc:
            self._append(
                "error",
                "Invalid posture payload ignored",
                {"topic": POSTURE_TOPIC, "error": str(exc), "payload": payload},
            )
            return
        with self._lock:
            self._last_posture = dict(payload)
            self._last_decision = decision
        self._append(
            "mqtt",
            "MQTT posture received",
            {"topic": POSTURE_TOPIC, **payload, **decision.as_dict()},
        )
        if decision.new_trigger:
            if now < self._trigger_retry_after:
                self._tracker.allow_trigger_retry()
                return
            self._append(
                "trigger",
                "Continuous-sitting threshold reached",
                decision.as_dict(),
            )
            try:
                result = self._on_threshold(decision)
            except Exception as exc:  # noqa: BLE001 - callback boundary must preserve bridge
                self._tracker.allow_trigger_retry()
                self._trigger_retry_after = now + 5.0
                self._append(
                    "error",
                    "Robot reminder trigger rejected",
                    {"error": str(exc), "error_type": type(exc).__name__},
                )
            else:
                self._trigger_retry_after = 0.0
                data = result if isinstance(result, dict) else None
                self._append("trigger", "Robot reminder job created", data)

    def _append(
        self,
        level: str,
        message: str,
        data: dict[str, object] | None,
    ) -> None:
        with self._lock:
            self._sequence += 1
            self._events.append(
                {
                    "sequence": self._sequence,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "level": level,
                    "message": message,
                    "data": data,
                }
            )
