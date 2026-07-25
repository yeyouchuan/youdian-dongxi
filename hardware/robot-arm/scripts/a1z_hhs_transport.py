"""macOS transport compatibility for the Galaxea HHS USB-CANFD adapter.

The public ``gs-usb`` package does not list the HHS VID/PID, assumes bulk OUT
endpoint 0x02 instead of the HHS endpoint 0x01, and attempts a Linux-only
kernel-driver detach operation on Darwin. The helpers here patch only those
transport mismatches for the current Python process.
"""

from __future__ import annotations

import platform
import time
from typing import Any

HHS_VENDOR_ID = 0xA8FA
HHS_PRODUCT_ID = 0x8598
HHS_OUT_ENDPOINT = 0x01
CAN_BITRATE = 1_000_000
MAX_ECHO_DRAIN = 16

_PATCHED = False


def patch_hhs_transport() -> None:
    """Make the upstream gs_usb Python transport recognize the HHS adapter."""
    global _PATCHED
    if _PATCHED:
        return

    from gs_usb.constants import GS_CAN_MODE_HW_TIMESTAMP
    from gs_usb.gs_usb import GsUsb

    original_match = GsUsb.is_gs_usb_device
    original_find = GsUsb.find
    original_send = GsUsb.send

    def is_supported_device(device: Any) -> bool:
        is_hhs = (
            device.idVendor == HHS_VENDOR_ID
            and device.idProduct == HHS_PRODUCT_ID
        )
        return is_hhs or original_match(device)

    def send_frame(device: Any, frame: Any) -> bool:
        raw_device = device.gs_usb
        if (
            raw_device.idVendor != HHS_VENDOR_ID
            or raw_device.idProduct != HHS_PRODUCT_ID
        ):
            return original_send(device, frame)
        has_timestamps = bool(
            device.device_flags & GS_CAN_MODE_HW_TIMESTAMP
        )
        raw_device.write(HHS_OUT_ENDPOINT, frame.pack(has_timestamps))
        return True

    def find_device(cls: Any, bus: int, address: int) -> Any:
        device = original_find(bus=bus, address=address)
        if (
            device is not None
            and platform.system() == "Darwin"
            and device.gs_usb.idVendor == HHS_VENDOR_ID
            and device.gs_usb.idProduct == HHS_PRODUCT_ID
        ):
            # Scope the Darwin workaround to this HHS instance. libusb cannot
            # detach a kernel driver on macOS, and this vendor interface is
            # already directly available to userspace.
            device.gs_usb.is_kernel_driver_active = lambda interface: False
        return device

    GsUsb.is_gs_usb_device = staticmethod(is_supported_device)
    GsUsb.find = classmethod(find_device)
    GsUsb.send = send_frame

    _PATCHED = True


def discard_tx_echoes(bus: Any) -> None:
    """Wrap ``bus.recv`` so gs_usb TX echoes never reach motor parsers.

    HHS reports transmitted frames with ``Message.is_rx == False`` and real
    motor feedback with ``is_rx == True``. For non-blocking reads, all queued
    echoes must be drained before returning ``None``; otherwise the SDK can
    continuously encounter its own echoes and starve real feedback.
    """
    raw_recv = bus.recv

    def recv_without_echo(timeout: float | None = None) -> Any:
        deadline = None if timeout is None else time.monotonic() + timeout
        first_read = True
        echoes_drained = 0
        while echoes_drained < MAX_ECHO_DRAIN:
            if timeout is None:
                wait = None
            elif first_read:
                wait = timeout
            else:
                if timeout > 0 and time.monotonic() >= deadline:
                    return None
                wait = max(0.0, deadline - time.monotonic())
            message = raw_recv(timeout=wait)
            first_read = False
            if message is None or message.is_rx:
                return message
            echoes_drained += 1
        return None

    bus.recv = recv_without_echo


def open_hhs_bus() -> Any:
    """Open the first HHS adapter at the A1Z classical-CAN bitrate."""
    import can
    import usb.core
    from usb.backend import libusb1

    patch_hhs_transport()
    usb_device = usb.core.find(
        idVendor=HHS_VENDOR_ID,
        idProduct=HHS_PRODUCT_ID,
        backend=libusb1.get_backend(),
    )
    if usb_device is None:
        raise RuntimeError("HHS USB-CANFD adapter a8fa:8598 was not found")
    bus = can.Bus(
        interface="gs_usb",
        channel=f"hhs-{usb_device.bus}-{usb_device.address}",
        bus=usb_device.bus,
        address=usb_device.address,
        bitrate=CAN_BITRATE,
    )
    discard_tx_echoes(bus)
    return bus
