"""Gradio GUI for the A1Z x G0.5 preliminary on-device validation harness.

Run on the macOS laptop (arm + wrist camera connected):

    pip install -r requirements.txt
    python -m a1z_g05.app --config config.yaml
    # open the printed http://127.0.0.1:7860 URL

The GUI lets you:
  - see the live wrist-camera feed,
  - type a natural-language command ("pick up the red block") and send it,
  - watch joint / gripper state, control rate, and the model's chain-of-thought,
  - Connect / Disconnect the G0.5 server and hit E-STOP at any time.

G0.5 inference runs on the remote GPU server (serve_policy.py); this app only
streams observations to it and applies the returned actions to the arm.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import gradio as gr
import numpy as np
import yaml

from a1z_g05.arm_interface import make_arm
from a1z_g05.camera import CameraWorker
from a1z_g05.controller import InferenceController
from a1z_g05.mapping import A1ZSo100Mapping, MappingConfig
from a1z_g05.retargeting import (
    KinematicRetargeter,
    PinocchioKinematics,
    RetargetingConfig,
)

logger = logging.getLogger(__name__)


def load_config(path: str) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


class App:
    """Holds the shared controller/camera and builds the Gradio Blocks UI."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        cam_cfg = cfg.get("camera", {})
        self.camera = CameraWorker(
            index=int(cam_cfg.get("index", 0)),
            width=int(cam_cfg.get("width", 640)),
            height=int(cam_cfg.get("height", 480)),
            fps=int(cam_cfg.get("fps", 30)),
            backend=str(cam_cfg.get("backend", "auto")),
            fourcc=cam_cfg.get("fourcc"),
            rotate_180=bool(cam_cfg.get("rotate_180", False)),
        )
        arm = make_arm(cfg.get("arm", {}))
        map_cfg = cfg.get("mapping", {})
        model_mapping = MappingConfig(
            arm_joint_indices=map_cfg.get("arm_joint_indices", [0, 1, 2, 3, 4]),
            signs=map_cfg.get("signs", [1, -1, 1, 1, 1]),
            scales=map_cfg.get("scales", [1, 1, 1, 1, 1]),
            offsets=map_cfg.get("offsets", [0, 90, 90, 0, 0]),
            gripper_deg_open=float(map_cfg.get("gripper_deg_open", 0.0)),
            gripper_deg_closed=float(map_cfg.get("gripper_deg_closed", 45.0)),
            dof=int(cfg.get("arm", {}).get("dof", 6)),
        )
        if map_cfg.get("mode", "direct") == "kinematic":
            kin_cfg = map_cfg.get("kinematic", {})
            mapping = KinematicRetargeter(
                RetargetingConfig(
                    model=model_mapping,
                    position_scale=float(kin_cfg["position_scale"]),
                    base_transform=np.asarray(kin_cfg["base_transform"], dtype=np.float64),
                    tool_transform=np.asarray(kin_cfg["tool_transform"], dtype=np.float64),
                ),
                PinocchioKinematics(kin_cfg["so100_urdf"], kin_cfg["so100_ee_frame"]),
                PinocchioKinematics(
                    kin_cfg["a1z_urdf"],
                    kin_cfg["a1z_ee_frame"],
                    locked_joint_indices=kin_cfg.get("a1z_locked_joint_indices", []),
                ),
            )
        else:
            mapping = A1ZSo100Mapping(model_mapping)
        self.controller = InferenceController(
            arm=arm,
            camera=self.camera,
            mapping=mapping,
            server=cfg.get("server", {}),
            control=cfg.get("control", {}),
            camera_cfg=cam_cfg,
        )

    # -- Gradio callbacks ---------------------------------------------------

    def on_connect(self) -> str:
        try:
            self.controller.start()
            return "Connected. Type a command and press Send."
        except Exception as exc:
            logger.exception("connect failed")
            return f"Connect failed: {exc}"

    def on_disconnect(self) -> str:
        self.controller.stop()
        return "Disconnected."

    def on_send(self, task: str) -> str:
        st = self.controller.status()
        if not st.running:
            return "Not connected. Click Connect first."
        self.controller.set_task(task)
        return f"Task sent: {task!r}"

    def on_estop(self) -> str:
        self.controller.set_estop(True)
        return "E-STOP engaged. Motion halted. Click Release to resume."

    def on_release_estop(self) -> str:
        self.controller.set_estop(False)
        return "E-STOP released."

    def poll(self):
        """Return (camera_rgb, status_markdown, cot_text) for periodic refresh."""
        frame = self.camera.read_rgb()
        if frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
        st = self.controller.status()
        joints = ", ".join(f"{j:+.3f}" for j in st.joints_rad) if st.joints_rad else "-"
        status_md = (
            f"**Running:** {st.running}  |  **Connected:** {st.connected}  |  "
            f"**E-stop:** {'🛑 ' if st.estopped else ''}{st.estopped}\n\n"
            f"**Task:** {st.task or '(none)'}\n\n"
            f"**Step:** {st.step}  |  **Rate:** {st.action_hz:.1f} Hz  |  "
            f"**Mode:** {'SHADOW' if st.shadow_mode else 'EXECUTE'} / "
            f"{'INFER' if st.need_obs else 'CACHE'}\n\n"
            f"**Joints (rad):** {joints}\n\n"
            f"**Gripper:** {st.gripper:.3f}"
        )
        if st.last_error:
            status_md += f"\n\n**⚠️ Last error:** {st.last_error}"
        return frame, status_md, (st.cot_text or "")

    # -- UI -----------------------------------------------------------------

    def build(self) -> gr.Blocks:
        server = self.cfg.get("server", {})
        title = "A1Z × G0.5 — preliminary control panel"
        with gr.Blocks(title=title) as demo:
            gr.Markdown(f"# {title}")
            gr.Markdown(
                f"G0.5 policy server: `ws://{server.get('host','localhost')}:"
                f"{server.get('port',8765)}` · arm backend: "
                f"`{self.cfg.get('arm',{}).get('backend','mock')}`"
            )
            with gr.Row():
                with gr.Column(scale=3):
                    cam = gr.Image(label="Wrist camera", height=380)
                with gr.Column(scale=2):
                    status = gr.Markdown("Not connected.")
                    cot = gr.Textbox(label="Model chain-of-thought", lines=4, interactive=False)
            with gr.Row():
                task = gr.Textbox(
                    label="Natural-language command",
                    placeholder="e.g. pick up the red block and place it in the tray",
                    scale=4,
                )
                send_btn = gr.Button("Send", variant="primary", scale=1)
            with gr.Row():
                connect_btn = gr.Button("Connect")
                disconnect_btn = gr.Button("Disconnect")
                estop_btn = gr.Button("🛑 E-STOP", variant="stop")
                release_btn = gr.Button("Release E-STOP")
            msg = gr.Markdown("")

            connect_btn.click(self.on_connect, outputs=msg)
            disconnect_btn.click(self.on_disconnect, outputs=msg)
            send_btn.click(self.on_send, inputs=task, outputs=msg)
            task.submit(self.on_send, inputs=task, outputs=msg)
            estop_btn.click(self.on_estop, outputs=msg)
            release_btn.click(self.on_release_estop, outputs=msg)

            # Periodic refresh of camera + telemetry (~5 Hz).
            timer = gr.Timer(0.2)
            timer.tick(self.poll, outputs=[cam, status, cot])
        return demo


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(description="A1Z x G0.5 Gradio control panel")
    p.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.yaml"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--share", action="store_true", help="expose a public Gradio link")
    args = p.parse_args()

    cfg = load_config(args.config)
    app = App(cfg)
    demo = app.build()
    try:
        demo.launch(server_name=args.host, server_port=args.port, share=args.share)
    finally:
        app.controller.stop()
        app.camera.release()


if __name__ == "__main__":
    main()
