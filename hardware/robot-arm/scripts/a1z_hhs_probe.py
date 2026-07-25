#!/usr/bin/env python3
"""Safely probe the Galaxea A1Z HHS USB-CANFD adapter on macOS.

The default action only enumerates the USB device and reads its gs_usb
capability descriptors. ``--listen-seconds`` additionally configures the
adapter for 1 Mbps listen-only mode. This script has no CAN transmit path and
never enables a motor.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from typing import Any

HHS_VENDOR_ID = 0xA8FA
HHS_PRODUCT_ID = 0x8598
CAN_BITRATE = 1_000_000


def usb_id(vendor_id: int, product_id: int) -> str:
    """Return a conventional lowercase USB VID:PID string."""
    return f"{vendor_id:04x}:{product_id:04x}"


def supports_mode(feature_flags: int, mode_flag: int) -> bool:
    """Return whether a gs_usb capability bit is present."""
    return feature_flags & mode_flag == mode_flag


def find_adapter() -> Any:
    """Find the first attached HHS adapter or exit with an actionable error."""
    import usb.core
    from usb.backend import libusb1

    adapter = usb.core.find(
        idVendor=HHS_VENDOR_ID,
        idProduct=HHS_PRODUCT_ID,
        backend=libusb1.get_backend(),
    )
    if adapter is None:
        raise RuntimeError(
            f"HHS adapter {usb_id(HHS_VENDOR_ID, HHS_PRODUCT_ID)} was not found"
        )
    return adapter


def probe(listen_seconds: float = 0.0) -> dict[str, Any]:
    """Read adapter descriptors and optionally perform a passive CAN listen."""
    from gs_usb.constants import GS_CAN_MODE_HW_TIMESTAMP, GS_CAN_MODE_LISTEN_ONLY
    from gs_usb.gs_usb import GsUsb
    from gs_usb.gs_usb_frame import GsUsbFrame

    adapter = find_adapter()
    device = GsUsb(adapter)
    device_info = device.device_info
    device_capability = device.device_capability
    result: dict[str, Any] = {
        "usb_id": usb_id(adapter.idVendor, adapter.idProduct),
        "serial_number": device.serial_number,
        "bus": adapter.bus,
        "address": adapter.address,
        "device_info": {
            "fw_version": device_info.fw_version,
            "hw_version": device_info.hw_version,
            "icount": device_info.icount,
        },
        "device_capability": {
            "feature": device_capability.feature,
            "fclk_can": device_capability.fclk_can,
            "brp_min": device_capability.brp_min,
            "brp_max": device_capability.brp_max,
            "brp_inc": device_capability.brp_inc,
            "tseg1_min": device_capability.tseg1_min,
            "tseg1_max": device_capability.tseg1_max,
            "tseg2_min": device_capability.tseg2_min,
            "tseg2_max": device_capability.tseg2_max,
            "sjw_max": device_capability.sjw_max,
        },
        "listen_only": False,
        "frames_received": 0,
    }

    if listen_seconds <= 0:
        return result

    # gs-usb 0.3.1 uses a Linux-style detach check on Darwin. libusb cannot
    # detach kernel drivers on macOS, while descriptor/control access to this
    # adapter already works. Bypass that inapplicable check only on Darwin.
    if platform.system() == "Darwin":
        adapter.is_kernel_driver_active = lambda _interface: False

    if not supports_mode(device_capability.feature, GS_CAN_MODE_LISTEN_ONLY):
        raise RuntimeError("adapter firmware does not support listen-only mode")
    if not device.set_bitrate(CAN_BITRATE):
        raise RuntimeError(f"adapter rejected {CAN_BITRATE} bit/s timing")

    frames: list[dict[str, Any]] = []
    started = False
    try:
        device.start(flags=GS_CAN_MODE_LISTEN_ONLY | GS_CAN_MODE_HW_TIMESTAMP)
        started = True
        if not supports_mode(device.device_flags, GS_CAN_MODE_LISTEN_ONLY):
            raise RuntimeError("adapter did not enter listen-only mode")
        deadline = time.monotonic() + listen_seconds
        while time.monotonic() < deadline:
            frame = GsUsbFrame()
            if device.read(frame, timeout_ms=100):
                frames.append(
                    {
                        "can_id": f"0x{frame.can_id:03x}",
                        "data": bytes(frame.data).hex(),
                    }
                )
    finally:
        if started:
            device.stop()

    result.update(
        {
            "listen_only": True,
            "listen_seconds": listen_seconds,
            "frames_received": len(frames),
            "frames": frames[:20],
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=0.0,
        help="passively listen at 1 Mbps; sends no CAN frames (default: disabled)",
    )
    args = parser.parse_args()
    if args.listen_seconds < 0:
        parser.error("--listen-seconds must be non-negative")

    try:
        result = probe(args.listen_seconds)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
