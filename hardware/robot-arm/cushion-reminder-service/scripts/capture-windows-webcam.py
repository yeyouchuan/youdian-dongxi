"""Capture color candidates from a native Windows webcam using DirectShow."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--index", type=int, choices=range(4))
    parser.add_argument("--min-mean", type=float, default=2.0)
    args = parser.parse_args()
    import cv2

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    indices = range(4) if args.index is None else (args.index,)
    for index in indices:
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        try:
            if not capture.isOpened():
                continue
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            capture.set(cv2.CAP_PROP_FPS, 30)
            frame = None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                ok, candidate = capture.read()
                if ok and candidate is not None:
                    frame = candidate
                    if float(candidate.mean()) > 2:
                        break
            if frame is None:
                continue
            mean = float(frame.mean())
            if mean < args.min_mean:
                rejected.append({"index": index, "reason": "black_frame", "mean": mean})
                continue
            output = output_dir / f"a1z-windows-camera-{index}.jpg"
            if not cv2.imwrite(str(output), frame):
                continue
            candidates.append(
                {
                    "index": index,
                    "path": str(output),
                    "width": int(frame.shape[1]),
                    "height": int(frame.shape[0]),
                    "mean": round(mean, 3),
                }
            )
        finally:
            capture.release()
    print(json.dumps({"candidates": candidates, "rejected": rejected}), flush=True)
    return 0 if candidates else 2


if __name__ == "__main__":
    raise SystemExit(main())
