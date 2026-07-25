from __future__ import annotations

import websockets.sync.client as ws_sync

from a1z_g05.g05_client import G05PolicyClient
from a1z_g05.msgpack_codec import packb


class FakeWebSocket:
    def __init__(self) -> None:
        self.responses = [
            packb({"action_steps": 16}),
            packb({"action": {"right_arm": [0, 0, 0, 0, 0, 0]}, "need_obs": False}),
        ]
        self.recv_timeouts: list[float | None] = []
        self.sent: list[bytes] = []

    def recv(self, timeout: float | None = None) -> bytes:
        self.recv_timeouts.append(timeout)
        return self.responses.pop(0)

    def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        return None


def test_long_inference_uses_application_request_timeout(
    monkeypatch,
) -> None:
    websocket = FakeWebSocket()
    connect_options: dict[str, object] = {}

    def fake_connect(uri: str, **kwargs: object) -> FakeWebSocket:
        connect_options.update(kwargs)
        return websocket

    monkeypatch.setattr(ws_sync, "connect", fake_connect)
    client = G05PolicyClient("127.0.0.1", 8765, timeout_s=60)

    client.connect()
    client.infer({})

    assert connect_options["open_timeout"] == 60.0
    assert websocket.recv_timeouts == [60.0, 60.0]
