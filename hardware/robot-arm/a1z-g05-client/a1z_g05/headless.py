"""Headless real-robot runner for the A1Z G0.5 bridge."""

from __future__ import annotations

import argparse
import logging
import signal
import time
from pathlib import Path
from typing import Any

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


def build_controller(cfg: dict[str, Any]) -> tuple[InferenceController, CameraWorker]:
    cam_cfg = cfg.get("camera", {})
    raw_camera_index = cam_cfg.get("index", 0)
    camera_index = (
        raw_camera_index
        if isinstance(raw_camera_index, str)
        else int(raw_camera_index)
    )
    camera = CameraWorker(
        index=camera_index,
        width=int(cam_cfg.get("width", 640)),
        height=int(cam_cfg.get("height", 480)),
        fps=int(cam_cfg.get("fps", 30)),
        backend=str(cam_cfg.get("backend", "auto")),
        fourcc=cam_cfg.get("fourcc"),
        rotate_180=bool(cam_cfg.get("rotate_180", False)),
    )
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
        kin_cfg = map_cfg["kinematic"]
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
    controller = InferenceController(
        arm=make_arm(cfg.get("arm", {})),
        camera=camera,
        mapping=mapping,
        server=cfg.get("server", {}),
        control=cfg.get("control", {}),
        camera_cfg=cam_cfg,
    )
    return controller, camera


def main() -> None:
    parser = argparse.ArgumentParser(description="Run G0.5 against the real A1Z")
    parser.add_argument("--config", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--max-steps", type=int, default=16)
    args = parser.parse_args()
    if args.max_steps <= 0:
        parser.error("--max-steps must be positive")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = yaml.safe_load(Path(args.config).read_text()) or {}
    cfg.setdefault("control", {})["max_steps"] = args.max_steps
    controller, camera = build_controller(cfg)
    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        controller.start()
        controller.set_task(args.task)
        while not stop:
            status = controller.status()
            print(
                f"step={status.step} hz={status.action_hz:.1f} "
                f"need_obs={status.need_obs} error={status.last_error or '-'}",
                flush=True,
            )
            if status.last_error:
                raise RuntimeError(status.last_error)
            if status.step >= args.max_steps:
                break
            time.sleep(0.5)
    finally:
        controller.stop()
        # Let the server's 350 ms stream watchdog settle to measured hold.
        time.sleep(0.5)
        camera.release()


if __name__ == "__main__":
    main()
