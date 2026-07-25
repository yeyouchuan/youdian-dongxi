#!/usr/bin/env python3
"""Run the official gripper free-travel sequence through the macOS HHS bus."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from typing import Any

from a1z.motor_drivers.motor_b_driver import MotorB
from a1z.motor_drivers.utils import MotorErrorCode
from a1z.robots.gripper import (
    GRIPPER_CAN_ID,
    GRIPPER_MOTOR_RANGES,
    Gripper,
)

from scripts.a1z_hhs_transport import open_hhs_bus

TARGETS = (("closed", 0.0), ("half", 0.5), ("open", 1.0))
TARGET_TOLERANCE = 0.10
TARGET_TIMEOUT_S = 3.0
DEFAULT_MAX_TORQUE_NM = 0.5


def drain_feedback(motor: MotorB, duration: float = 0.02) -> None:
    """Drain gripper feedback frames without consuming unrelated CAN IDs."""
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        message = motor.bus.recv(timeout=0.0)
        if message is None:
            return
        if int(message.arbitration_id) != motor.motor_id:
            continue
        feedback = motor.parse_feedback(message)
        if feedback is not None:
            motor.last_feedback = feedback


def control_loop(
    gripper: Gripper,
    motor: MotorB,
    stop: threading.Event,
    errors: list[BaseException],
) -> None:
    """Send official hybrid commands at approximately 100 Hz."""
    try:
        while not stop.is_set():
            drain_feedback(motor, duration=0.002)
            gripper.step()
            time.sleep(0.01)
    except BaseException as exc:
        errors.append(exc)
        stop.set()


def wait_for_target(
    gripper: Gripper,
    motor: MotorB,
    target: float,
    stop: threading.Event,
    errors: list[BaseException],
) -> float:
    """Require fresh, fault-free feedback at the requested normalized target."""
    deadline = time.monotonic() + TARGET_TIMEOUT_S
    while time.monotonic() < deadline:
        if errors:
            raise RuntimeError("gripper control loop failed") from errors[0]
        if stop.is_set():
            raise RuntimeError("gripper test aborted")
        feedback = motor.last_feedback
        if feedback is not None:
            if int(feedback.error) not in (
                MotorErrorCode.disabled,
                MotorErrorCode.normal,
            ):
                raise RuntimeError(
                    f"gripper motor fault: {feedback.error_message}"
                )
            normalized = gripper.get_feedback_norm()
            logging.info(
                "target=%.1f feedback=%.3f torque=%+.2f Nm vel=%+.2f rad/s",
                target,
                normalized,
                feedback.torque,
                feedback.velocity,
            )
            if abs(normalized - target) <= TARGET_TOLERANCE:
                return normalized
        time.sleep(0.05)
    raise RuntimeError(
        f"gripper did not reach {target:.1f} within {TARGET_TIMEOUT_S:.1f}s"
    )


def run(max_torque_nm: float) -> None:
    """Enable only the gripper, run close/half/open, then open and disable."""
    bus = open_hhs_bus()
    motor = MotorB(
        motor_id=GRIPPER_CAN_ID,
        bus=bus,
        ranges=GRIPPER_MOTOR_RANGES,
    )
    gripper = Gripper(motor, max_torque=max_torque_nm)
    stop = threading.Event()
    errors: list[BaseException] = []
    thread = threading.Thread(
        target=control_loop,
        args=(gripper, motor, stop, errors),
        daemon=True,
    )
    enabled = False

    def handle_signal(signum: int, _frame: Any) -> None:
        logging.warning("Signal %s: opening and disabling gripper", signum)
        stop.set()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        gripper.enable()
        enabled = True
        time.sleep(0.1)
        drain_feedback(motor, duration=0.1)
        if motor.last_feedback is None:
            raise RuntimeError("no gripper feedback after enable")
        logging.info(
            "Gripper enabled at %+.3f rad status=%s",
            motor.last_feedback.position,
            motor.last_feedback.error_message,
        )
        if not gripper.home():
            raise RuntimeError("gripper failed to home open")
        thread.start()
        for label, target in TARGETS:
            logging.info("Commanding %s target=%.1f", label, target)
            gripper.command(target)
            measured = wait_for_target(
                gripper,
                motor,
                target,
                stop,
                errors,
            )
            logging.info("Reached %s feedback=%.3f", label, measured)
            time.sleep(0.25)
        logging.info("Gripper free-travel test passed")
    finally:
        if enabled:
            gripper.command(1.0)
            if thread.is_alive():
                time.sleep(0.5)
            else:
                for _ in range(30):
                    drain_feedback(motor, duration=0.002)
                    gripper.step()
                    time.sleep(0.01)
            stop.set()
            if thread.is_alive():
                thread.join(timeout=1.0)
            gripper.disable()
        bus.shutdown()
        logging.info("Gripper open command issued and motor disabled")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--torque",
        type=float,
        default=DEFAULT_MAX_TORQUE_NM,
    )
    parser.add_argument("--confirm-clear", action="store_true")
    args = parser.parse_args()
    if not args.confirm_clear:
        parser.error("--confirm-clear is required for active gripper motion")
    if not 0 < args.torque <= DEFAULT_MAX_TORQUE_NM:
        parser.error(
            f"--torque must be in (0, {DEFAULT_MAX_TORQUE_NM:.1f}] Nm"
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run(args.torque)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
