"""Synchronous WebSocket client for the GalaxeaVLA G0.5 policy server.

The server (`scripts/serve_policy.py`) speaks msgpack over a WebSocket and
manages an internal action-chunk cache (``ChunkedPolicyWrapper``). The protocol
observed from the reference clients (experiments/so100, experiments/r1lite):

Handshake
    On connect the server immediately sends one msgpack message: metadata,
    e.g. ``{"action_steps": 32, ...}``.

Inference request  (client -> server)
    Full observation, requesting a fresh inference:
        {
          "images": {server_key: np.ndarray[C,H,W] uint8, ...},
          "state":  {"right_arm": np.ndarray[6] float32},   # model-frame degrees
          "task":   "pick up the red block",
          "embodiment_type": "so100",
          "frequency": 15.0,
        }
    Cache request (server returns the next step of the current chunk):
        {}                       # empty dict

Inference response (server -> client)
    {
      "action":   {"right_arm": np.ndarray[6] float32},   # model-frame degrees
      "need_obs": bool,          # True -> send a full obs next tick
      "cot_text": str | None,    # optional chain-of-thought
    }
    or {"error": {...}} on failure.

This client is deliberately synchronous (``websockets.sync.client``) so it can
be driven from a plain background thread in the Gradio app without an asyncio
event loop.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

from a1z_g05.msgpack_codec import packb, unpackb

logger = logging.getLogger(__name__)


class G05PolicyClient:
    """Thin synchronous client around the G0.5 WebSocket policy server."""

    def __init__(self, host: str, port: int, timeout_s: float = 30.0) -> None:
        if host.startswith("ws://") or host.startswith("wss://"):
            self.uri = host if port is None else f"{host}:{port}"
        else:
            self.uri = f"ws://{host}:{port}" if port is not None else f"ws://{host}"
        self.timeout_s = float(timeout_s)
        self._ws: Any = None
        self.metadata: dict[str, Any] = {}

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> dict[str, Any]:
        """Open the connection and read the server handshake metadata."""
        import websockets.sync.client as ws_sync

        # serve_policy.py does not use a proxy; strip proxy env vars that would
        # otherwise make websockets try to CONNECT through one (matches r1lite).
        saved = {k: os.environ.pop(k, None) for k in ("http_proxy", "https_proxy", "all_proxy")}
        try:
            self._ws = ws_sync.connect(
                self.uri,
                compression=None,
                max_size=None,
                open_timeout=self.timeout_s,
            )
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

        handshake = self._ws.recv(timeout=self.timeout_s)
        self.metadata = unpackb(handshake) if handshake else {}
        logger.info("[G05PolicyClient] connected to %s, metadata=%s", self.uri, self.metadata)
        return self.metadata

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    @property
    def action_steps(self) -> int:
        """Chunk length reported by the server (default 1 if not advertised)."""
        return int(self.metadata.get("action_steps", 1))

    # -- inference ----------------------------------------------------------

    def infer(self, raw_obs: dict[str, Any]) -> dict[str, Any]:
        """Send an observation (or ``{}`` for a cached step) and return the reply."""
        if self._ws is None:
            raise RuntimeError("G05PolicyClient is not connected")
        self._ws.send(packb(raw_obs))
        response = self._ws.recv(timeout=self.timeout_s)
        if isinstance(response, str):
            # serve_policy.py sends plain-text on fatal server errors.
            raise RuntimeError(f"policy server error: {response}")
        result = unpackb(response)
        if isinstance(result, dict) and "error" in result:
            err = result["error"]
            msg = err.get("message", err) if isinstance(err, dict) else err
            raise RuntimeError(f"policy server error: {msg}")
        return result

    def reset(self) -> None:
        """Ask the server to drop any cached chunk / reset policy state."""
        if self._ws is None:
            raise RuntimeError("G05PolicyClient is not connected")
        self._ws.send(packb({"__reset__": True}))
        self._ws.recv(timeout=self.timeout_s)  # drain ack

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "G05PolicyClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_obs(
    *,
    images: dict[str, np.ndarray],
    state_model_deg: np.ndarray,
    task: str,
    embodiment_type: str,
    frequency: float,
    state_key: str = "right_arm",
) -> dict[str, Any]:
    """Assemble the full observation dict expected by serve_policy.py.

    Args:
        images: mapping of server image key -> uint8 ndarray of shape (C, H, W).
        state_model_deg: model-frame proprio vector (degrees), float32.
        task: natural-language instruction.
        embodiment_type: e.g. "so100".
        frequency: control loop frequency in Hz.
        state_key: state sub-key the checkpoint expects ("right_arm" for so100).
    """
    return {
        "images": {k: np.ascontiguousarray(v, dtype=np.uint8) for k, v in images.items()},
        "state": {state_key: np.asarray(state_model_deg, dtype=np.float32)},
        "task": task,
        "embodiment_type": embodiment_type,
        "frequency": float(frequency),
    }
