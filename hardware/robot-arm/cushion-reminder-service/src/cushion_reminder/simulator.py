"""Local MQTT publisher that mimics the SmartCushion firmware contracts."""

from __future__ import annotations

import argparse
import json
import random
import signal
import statistics
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any, Protocol

POSTURE_TOPIC = "zuodian/posture"
RADAR_TOPIC = "zuodian/radar"
SUPPORTED_POSES = ("AWAY", "UPRIGHT", "LEAN_L", "LEAN_R", "EDGE", "OTHER")

_POSTURE_BASES: dict[str, dict[str, int]] = {
    "AWAY": {"s1": 1, "s3": 1, "s4": 1, "s5": 1, "s6": 1},
    "UPRIGHT": {"s1": 220, "s3": 90, "s4": 210, "s5": 135, "s6": 130},
    "LEAN_L": {"s1": 390, "s3": 80, "s4": 95, "s5": 250, "s6": 65},
    "LEAN_R": {"s1": 95, "s3": 80, "s4": 390, "s5": 65, "s6": 250},
    "EDGE": {"s1": 240, "s3": 230, "s4": 235, "s5": 35, "s6": 35},
    "OTHER": {"s1": 185, "s3": 165, "s4": 250, "s5": 105, "s6": 170},
}


class Publisher(Protocol):
    def publish(self, topic: str, payload: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


class CushionSimulator:
    """Stateful generator for the two MQTT payloads emitted by the firmware."""

    def __init__(self, *, seed: int = 1, pose: str = "UPRIGHT") -> None:
        if pose not in SUPPORTED_POSES:
            raise ValueError(f"Unsupported pose {pose!r}; choose one of {SUPPORTED_POSES}")
        self._random = random.Random(seed)
        self.pose = pose
        self.seq = 0
        self._heart_window: deque[float] = deque(maxlen=60)
        self._breath_window: deque[float] = deque(maxlen=60)
        self._last_radar: dict[str, float | int] | None = None

    def posture_payload(self) -> dict[str, int | str]:
        base = _POSTURE_BASES[self.pose]
        jitter = 7 if self.pose == "AWAY" else 18
        payload: dict[str, int | str] = {
            field: max(0, min(4095, value + self._random.randint(-jitter, jitter)))
            for field, value in base.items()
        }
        payload["pose"] = self.pose
        return payload

    def radar_payload(self, *, fresh: bool) -> dict[str, float | int]:
        if not fresh:
            if self._last_radar is None:
                raise RuntimeError("Cannot emit a stale keepalive before the first fresh frame")
            return dict(self._last_radar)

        self.seq += 1
        valid_heart = round(self._random.gauss(82.0, 4.0), 1)
        valid_breath = round(self._random.gauss(16.5, 1.2), 1)
        self._heart_window.append(valid_heart)
        self._breath_window.append(valid_breath)

        # The real module occasionally emits implausible instantaneous values.
        # Median fields remain based only on physiologically valid samples.
        heart = (
            round(self._random.uniform(155.0, 190.0), 1)
            if self._random.random() < 0.08
            else valid_heart
        )
        breath = (
            round(self._random.uniform(1.0, 3.0), 1)
            if self._random.random() < 0.08
            else valid_breath
        )
        payload: dict[str, float | int] = {
            "heart": heart,
            "heart_med": round(statistics.median(self._heart_window), 1),
            "breath": breath,
            "breath_med": round(statistics.median(self._breath_window), 1),
            "dist": round(self._random.uniform(68.0, 82.0), 1),
            "seq": self.seq,
        }
        self._last_radar = payload
        return dict(payload)


def radar_publish_interval(fresh: bool) -> float:
    """Match firmware cadence: 1 Hz for fresh frames, 5 s for keepalives."""
    return 1.0 if fresh else 5.0


class StdoutPublisher:
    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        print(f"{topic} {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}")

    def close(self) -> None:
        return None


class MqttPublisher:
    def __init__(self, *, host: str, port: int, qos: int, client_id: str) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError(
                "paho-mqtt is required for broker publishing; install this project first"
            ) from exc

        self._qos = qos
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        self._connected = threading.Event()

        def on_connect(
            client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any
        ) -> None:
            del client, userdata, flags, properties
            if reason_code == 0:
                self._connected.set()

        self._client.on_connect = on_connect
        self._client.connect(host, port, keepalive=30)
        self._client.loop_start()
        if not self._connected.wait(timeout=5):
            self.close()
            raise RuntimeError(f"MQTT broker {host}:{port} did not accept the connection")

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        info = self._client.publish(topic, encoded, qos=self._qos, retain=False)
        info.wait_for_publish(timeout=5)
        if info.rc != 0:
            raise RuntimeError(f"MQTT publish failed for {topic}: rc={info.rc}")
        print(f"{topic} {encoded}")

    def close(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()


def run_simulator(
    simulator: CushionSimulator,
    publisher: Publisher,
    *,
    duration: float | None,
    stale_after: float | None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    started_at = clock()
    next_posture = started_at
    next_radar = started_at
    stop_requested = False

    def request_stop(signum: int, frame: Any) -> None:
        del signum, frame
        nonlocal stop_requested
        stop_requested = True

    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    try:
        while not stop_requested:
            now = clock()
            elapsed = now - started_at
            if duration is not None and elapsed >= duration:
                break

            if now >= next_posture:
                publisher.publish(POSTURE_TOPIC, simulator.posture_payload())
                next_posture = now + 0.5

            if now >= next_radar:
                fresh = simulator.seq == 0 or stale_after is None or elapsed < stale_after
                publisher.publish(RADAR_TOPIC, simulator.radar_payload(fresh=fresh))
                next_radar = now + radar_publish_interval(fresh)

            next_due = min(next_posture, next_radar)
            sleep(max(0.01, min(0.1, next_due - clock())))
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        publisher.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="MQTT broker hostname")
    parser.add_argument("--port", default=1883, type=int, help="MQTT TCP port")
    parser.add_argument("--qos", default=0, choices=(0, 1), type=int)
    parser.add_argument("--pose", default="UPRIGHT", choices=SUPPORTED_POSES)
    parser.add_argument("--seed", default=1, type=int)
    parser.add_argument("--duration", type=float, help="Stop after N seconds")
    parser.add_argument(
        "--radar-stale-after",
        type=float,
        help="After N seconds, publish cached radar frames every 5 s without advancing seq",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print messages without connecting to a broker",
    )
    parser.add_argument("--client-id", default="smartcushion-local-simulator")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.duration is not None and args.duration <= 0:
        raise SystemExit("--duration must be greater than zero")
    if args.radar_stale_after is not None and args.radar_stale_after < 0:
        raise SystemExit("--radar-stale-after cannot be negative")

    simulator = CushionSimulator(seed=args.seed, pose=args.pose)
    publisher: Publisher
    if args.stdout:
        publisher = StdoutPublisher()
    else:
        publisher = MqttPublisher(
            host=args.host,
            port=args.port,
            qos=args.qos,
            client_id=args.client_id,
        )
    run_simulator(
        simulator,
        publisher,
        duration=args.duration,
        stale_after=args.radar_stale_after,
    )


if __name__ == "__main__":
    main()
