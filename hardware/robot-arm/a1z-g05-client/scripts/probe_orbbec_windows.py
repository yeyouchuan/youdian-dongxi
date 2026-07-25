"""Probe an Orbbec camera from native Windows Python and save one color frame."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pyorbbecsdk as ob


def call_first(obj: object, names: tuple[str, ...], default: object = None) -> object:
    for name in names:
        method = getattr(obj, name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                continue
    return default


def frame_to_bgr(frame: object) -> np.ndarray:
    width = int(call_first(frame, ("get_width", "width"), 0))
    height = int(call_first(frame, ("get_height", "height"), 0))
    data = np.frombuffer(frame.get_data(), dtype=np.uint8)
    frame_format = str(call_first(frame, ("get_format", "format"), "")).upper()
    if "MJPG" in frame_format or "MJPEG" in frame_format:
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    elif "RGB" in frame_format and width and height:
        image = cv2.cvtColor(data.reshape(height, width, 3), cv2.COLOR_RGB2BGR)
    elif ("BGR" in frame_format or not frame_format) and width and height:
        image = data.reshape(height, width, 3)
    elif ("YUYV" in frame_format or "YUY2" in frame_format) and width and height:
        image = cv2.cvtColor(data.reshape(height, width, 2), cv2.COLOR_YUV2BGR_YUY2)
    else:
        raise RuntimeError(
            f"Unsupported color format {frame_format!r}, size={width}x{height}, bytes={data.size}"
        )
    if image is None:
        raise RuntimeError(f"Failed to decode color frame format {frame_format!r}")
    return image


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "orbbec_color.jpg")
    report: dict[str, object] = {"sdk": getattr(ob, "__file__", ""), "devices": []}
    context = ob.Context()
    devices = context.query_devices()
    count = int(call_first(devices, ("get_count", "get_device_count"), 0))
    for index in range(count):
        device = devices.get_device_by_index(index)
        info = device.get_device_info()
        report["devices"].append(
            {
                "index": index,
                "name": call_first(info, ("get_name",), "unknown"),
                "serial": call_first(info, ("get_serial_number",), "unknown"),
                "vid": call_first(info, ("get_vid",), "unknown"),
                "pid": call_first(info, ("get_pid",), "unknown"),
                "firmware": call_first(info, ("get_firmware_version",), "unknown"),
            }
        )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if count == 0:
        fallback = []
        profiles = ((640, 480, ""), (640, 480, "MJPG"), (1920, 1080, "MJPG"))
        for index in range(10):
            opened = False
            for width, height, fourcc in profiles:
                capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                try:
                    if not capture.isOpened():
                        continue
                    opened = True
                    if fourcc:
                        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
                    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                    capture.set(cv2.CAP_PROP_FPS, 30)
                    image = None
                    for _ in range(30):
                        ok, candidate = capture.read()
                        if ok and candidate is not None:
                            image = candidate
                            if float(candidate.mean()) > 1:
                                break
                    if image is None:
                        continue
                    suffix = fourcc.lower() or "default"
                    path = output.with_name(
                        f"{output.stem}_dshow_{index}_{width}x{height}_{suffix}{output.suffix}"
                    )
                    cv2.imwrite(str(path), image)
                    fallback.append(
                        {
                            "index": index,
                            "profile": f"{width}x{height} {fourcc or 'default'}",
                            "frame": str(path),
                            "width": int(image.shape[1]),
                            "height": int(image.shape[0]),
                            "mean": float(image.mean()),
                        }
                    )
                finally:
                    capture.release()
            if not opened:
                continue
        print(json.dumps({"directshow": fallback}), flush=True)
        return 0 if fallback else 2

    pipeline = ob.Pipeline()
    pipeline.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            frames = pipeline.wait_for_frames(1000)
            if frames is None:
                continue
            color = frames.get_color_frame()
            if color is None:
                continue
            image = frame_to_bgr(color)
            output.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(output), image):
                raise RuntimeError(f"Failed to write {output}")
            print(
                json.dumps(
                    {
                        "frame": str(output),
                        "width": int(image.shape[1]),
                        "height": int(image.shape[0]),
                        "mean": float(image.mean()),
                    }
                ),
                flush=True,
            )
            return 0
    finally:
        pipeline.stop()
    raise RuntimeError("No Orbbec color frame received within 10 seconds")


if __name__ == "__main__":
    raise SystemExit(main())
