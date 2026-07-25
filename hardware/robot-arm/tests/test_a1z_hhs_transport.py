from collections import deque
from types import SimpleNamespace

from scripts.a1z_hhs_transport import MAX_ECHO_DRAIN, discard_tx_echoes


class _FakeBus:
    def __init__(self, messages: list[object]) -> None:
        self.messages = deque(messages)
        self.timeouts: list[float | None] = []

    def recv(self, timeout: float | None = None) -> object | None:
        self.timeouts.append(timeout)
        return self.messages.popleft() if self.messages else None


def test_discard_tx_echoes_returns_real_feedback() -> None:
    echo = SimpleNamespace(is_rx=False)
    feedback = SimpleNamespace(is_rx=True)
    bus = _FakeBus([echo, echo, feedback])

    discard_tx_echoes(bus)

    assert bus.recv(timeout=0.0) is feedback
    assert bus.timeouts == [0.0, 0.0, 0.0]


def test_discard_tx_echoes_returns_none_after_only_echoes() -> None:
    echo = SimpleNamespace(is_rx=False)
    bus = _FakeBus([echo])

    discard_tx_echoes(bus)

    assert bus.recv(timeout=0.0) is None
    assert bus.timeouts == [0.0, 0.0]


def test_discard_tx_echoes_has_a_hard_drain_limit() -> None:
    echoes = [SimpleNamespace(is_rx=False)] * (MAX_ECHO_DRAIN + 5)
    bus = _FakeBus(echoes)

    discard_tx_echoes(bus)

    assert bus.recv(timeout=0.0) is None
    assert len(bus.timeouts) == MAX_ECHO_DRAIN
