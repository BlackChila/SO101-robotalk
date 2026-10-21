"""Explicit UI torque hold and release for the calibrated SO-101 follower.

This process never commands a new pose: it sets the measured position as the
hold goal before enabling torque. The separate --off-once path can release
torque left enabled by an earlier process, with register readback.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import select
import signal
import sys
import termios
import time
from pathlib import Path

from flux3_start_pose import FluxStartController
from flux3_ui_reset import (ARM_TRACKING_LIMIT_DEG, GRIPPER_TRACKING_LIMIT_PERCENT,
                            MAX_HOLD_SECONDS, assert_goal_echo,
                            assert_measured_in_bounds)


def enable_hold(controller: FluxStartController) -> dict:
    controller.connect()
    measured = controller.read("Present_Position")
    assert_measured_in_bounds(measured, controller.bounds)
    controller.robot.bus.sync_write("Goal_Position", measured)
    assert_goal_echo(controller, measured)
    controller.armed = True  # Cleanup covers a partially successful enable.
    controller.robot.bus.enable_torque(num_retry=1)
    controller.health(expect_torque=1)
    return measured


def hold_until_release(controller: FluxStartController, target: dict) -> str:
    deadline = time.monotonic() + MAX_HOLD_SECONDS
    while time.monotonic() < deadline:
        controller.health(expect_torque=1)
        actual = controller.read("Present_Position")
        for name, value in actual.items():
            limit = GRIPPER_TRACKING_LIMIT_PERCENT if name == "gripper" else ARM_TRACKING_LIMIT_DEG
            if abs(value - target[name]) > limit:
                raise RuntimeError(f"Hold position changed: {name}={value}")
        if select.select([sys.stdin], [], [], 0.2)[0]:
            command = sys.stdin.readline()
            if not command or command.strip().lower() == "r":
                return "operator_release" if command else "api_disconnected"
    return "hold_timeout"


def turn_off_once(controller: FluxStartController) -> dict:
    """Release a calibrated follower even if an old holder left torque on."""
    bus = controller.robot.bus
    bus.connect()
    try:
        fcntl.ioctl(bus.port_handler.ser.fileno(), termios.TIOCEXCL)
        if not bus.is_calibrated:
            raise RuntimeError("Follower calibration mismatch")
        before = controller.read("Torque_Enable", normalized=False)
        controller.armed = any(before.values())
        if controller.armed:
            bus.disable_torque(num_retry=3)
            controller.armed = False
        after = controller.read("Torque_Enable", normalized=False)
        if any(after.values()):
            raise RuntimeError(f"Torque-off readback failed: {after}; use power cutoff")
        return {"before": before, "after": after}
    finally:
        bus.disconnect(disable_torque=False)


def run(report_path: Path, *, off_once: bool = False) -> int:
    report = {"outcome": "aborted", "mode": "ui_torque_off" if off_once else "ui_torque_hold",
              "started_at_unix": time.time()}
    controller = None
    try:
        controller = FluxStartController()
        if off_once:
            report.update(turn_off_once(controller))
            report["outcome"] = "torque_off_verified"
        else:
            measured = enable_hold(controller)
            report["held_position"] = measured
            report["outcome"] = "torque_holding"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            print("SO101_UI_TORQUE_HOLDING", flush=True)
            report["release_reason"] = hold_until_release(controller, measured)
            report["outcome"] = "torque_released"
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if controller is not None and not off_once:
            try:
                controller.close()
            except BaseException as exc:
                report["outcome"] = "aborted"
                report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        report["ended_at_unix"] = time.time()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"outcome": report["outcome"], "error": report.get("error"),
                          "cleanup_error": report.get("cleanup_error")}, ensure_ascii=False), flush=True)
    return 0 if report["outcome"] in {"torque_released", "torque_off_verified"} else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--off-once", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(run(args.report, off_once=args.off_once))


if __name__ == "__main__":
    main()
