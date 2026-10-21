#!/usr/bin/env python3
"""Supervised SO-101 Leader teleoperation with a verified Follower hold on exit."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import select
import signal
import sys
import termios
import time
from pathlib import Path


from demo_intro_capture import (LEADER_CALIBRATION, LEADER_PORT, hold_follower,
                                require_leader_torque_off)
from flux3_joint_frame import NAMES
from flux3_start_pose import FluxStartController, plan_reset


def clamp_leader_action(action: dict, bounds: dict) -> tuple[dict, list[str]]:
    """Bound UI teleoperation targets without changing the shared calibration."""
    if set(action) != {f"{name}.pos" for name in NAMES}:
        raise RuntimeError("Incomplete Leader action")
    target = {}
    limited = []
    for name in NAMES:
        value = float(action[f"{name}.pos"])
        low, high = bounds[name]
        if not math.isfinite(value):
            raise RuntimeError(f"Nonfinite Leader position: {name}")
        target[name] = min(high, max(low, value))
        if target[name] != value:
            limited.append(name)
    return target, limited


def prepare_teleop_start(controller: FluxStartController, target: dict) -> dict:
    """Align to this UI run's bounded target; shared capture/replay stays strict."""
    current = controller.read("Present_Position")
    plan = plan_reset(current, target, controller.bounds)
    bus = controller.robot.bus
    bus.sync_write("Goal_Position", current)
    if not controller.armed:
        controller.armed = True
        bus.enable_torque(num_retry=1)
    controller.health(expect_torque=1)
    print(f"PREPARE_START steps={len(plan)}; keep the Leader still until ready.", flush=True)
    for index, goal in enumerate(plan):
        tick = time.monotonic()
        bus.sync_write("Goal_Position", goal)
        if index % 10 == 0:
            controller.health(expect_torque=1)
        time.sleep(max(0, 0.05 - (time.monotonic() - tick)))
    time.sleep(0.4)
    controller.health(expect_torque=1)
    return {"from": current, "leader_start": target,
            "measured_start": controller.read("Present_Position"),
            "duration_s": len(plan) / 20 + 0.4}


def pace_teleoperation(next_tick: float, period: float) -> float:
    """Skip missed deadlines; never accumulate delay or replay missed commands."""
    deadline = next_tick + period
    now = time.monotonic()
    if deadline <= now:
        return now
    time.sleep(deadline - now)
    return deadline


def create_leader():
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

    return SO101Leader(SO101LeaderConfig(
        port=LEADER_PORT, id="leader_main", calibration_dir=Path(LEADER_CALIBRATION),
        use_degrees=True, num_read_retries=5,
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Read alignment and motor state without enabling torque")
    parser.add_argument("--fps", type=float, default=50.0)
    parser.add_argument("--report", type=Path, help="Write start/stop state for the local UI")
    args = parser.parse_args()
    if not 20 <= args.fps <= 60:
        parser.error("--fps must be between 20 and 60")

    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    controller = FluxStartController()
    leader = create_leader()
    result = "PREFLIGHT_FAILED"
    hold_ok = None
    error = None
    limited_joints = []

    def report(state: str) -> None:
        if args.report is None:
            return
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "state": state, "pid": os.getpid(), "hold_verified": hold_ok,
            "error": error, "updated_at_unix": time.time(),
            "limited_joints": limited_joints,
            "message": (("Teleoperation is running · joint limit reached: " + ", ".join(limited_joints)
                         if limited_joints else "Teleoperation is running. The Follower follows the Leader.")
                        if state == "active" else None),
        }) + "\n")
        temporary.replace(args.report)

    report("starting")
    try:
        controller.robot.bus.connect()
        fcntl.ioctl(controller.robot.bus.port_handler.ser.fileno(), termios.TIOCEXCL)
        if not controller.robot.bus.is_calibrated:
            raise RuntimeError("Follower calibration mismatch")
        torque = controller.read("Torque_Enable", normalized=False)
        if set(torque.values()) not in ({0}, {1}):
            raise RuntimeError(f"Mixed Follower torque state: {torque}")
        controller.armed = set(torque.values()) == {1}
        controller.health(expect_torque=1 if controller.armed else 0)

        leader.bus.connect()
        fcntl.ioctl(leader.bus.port_handler.ser.fileno(), termios.TIOCEXCL)
        if not leader.is_calibrated:
            raise RuntimeError("Leader calibration mismatch")
        require_leader_torque_off(leader)

        measured = controller.read("Present_Position")
        action = leader.get_action()
        if set(action) != {f"{name}.pos" for name in NAMES}:
            raise RuntimeError("Incomplete Leader position")
        target = {name: float(action[f"{name}.pos"]) for name in NAMES}
        alignment_error = {name: target[name] - measured[name] for name in NAMES}
        if not all(math.isfinite(value) for value in alignment_error.values()):
            raise RuntimeError("Nonfinite Leader/Follower position")
        if args.check_only:
            print(f"FOLLOWER_TORQUE {torque}", flush=True)
            print(f"FOLLOWER_GOAL {controller.read('Goal_Position')}", flush=True)
        print(f"ALIGNMENT follower={measured} leader={target} error={alignment_error}", flush=True)
        if args.check_only:
            result = "CHECK_OK"
            return 0
        target, limited_joints = clamp_leader_action(action, controller.bounds)
        alignment_error = {name: target[name] - measured[name] for name in NAMES}
        needs_alignment = False
        for name in NAMES:
            limit = 10.0 if name == "gripper" else 5.0
            if abs(alignment_error[name]) > limit:
                needs_alignment = True
            maximum = 15.0
            if abs(alignment_error[name]) > maximum:
                raise RuntimeError(f"Leader/Follower difference too large for slow alignment: {name} error={alignment_error[name]:.2f}")

        if needs_alignment:
            print("SLOW_ALIGNMENT_START Keep the Leader still.", flush=True)
            preparation = prepare_teleop_start(controller, target)
            print(f"SLOW_ALIGNMENT_DONE {preparation}", flush=True)
            if any(abs(preparation["measured_start"][name] - target[name]) >
                   (4.0 if name == "gripper" else 2.0) for name in NAMES):
                raise RuntimeError("Follower did not reach the Leader start pose")
        else:
            # Latch the measured position before enabling any motor torque.
            controller.robot.bus.sync_write("Goal_Position", measured)
            if not controller.armed:
                controller.armed = True
                controller.robot.bus.enable_torque(num_retry=1)
        hold_follower(controller)
        print("TELEOP_ACTIVE Follower follows the Leader. Enter q or press Ctrl+C to stop and hold.", flush=True)
        report("active")
        result = "STOPPED"
        next_tick = time.monotonic()
        count = 0
        last_report = time.monotonic()
        reported_limits = tuple(limited_joints)
        while True:
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                command = line.strip().lower()
                if not line or command in {"q", "x", "stop"}:
                    break
            action = leader.get_action()
            target, limited_joints = clamp_leader_action(action, controller.bounds)
            controller.robot.bus.sync_write("Goal_Position", target)
            count += 1
            if count % 25 == 0:
                controller.health(expect_torque=1)
            # Report limit changes at most four times a second, outside motor I/O.
            now = time.monotonic()
            if tuple(limited_joints) != reported_limits and now - last_report >= 0.25:
                report("active")
                reported_limits = tuple(limited_joints)
                last_report = now
            next_tick = pace_teleoperation(next_tick, 1 / args.fps)
    except KeyboardInterrupt:
        result = "STOPPED"
    except BaseException as exc:
        result = "ABORTED"
        error = f"{type(exc).__name__}: {exc}"
        print(f"TELEOP_ERROR {type(exc).__name__}: {exc}", flush=True)
    finally:
        if controller.robot.bus.is_connected:
            try:
                if controller.armed and not args.check_only:
                    held = hold_follower(controller)
                    hold_ok = True
                    print(f"FOLLOWER_HOLD_VERIFIED measured={held} torque=1", flush=True)
            except BaseException as exc:
                hold_ok = False
                error = f"Follower hold unverified: {type(exc).__name__}: {exc}"
                print(f"FOLLOWER_HOLD_UNVERIFIED {type(exc).__name__}: {exc}", flush=True)
            finally:
                try:
                    controller.robot.bus.disconnect(disable_torque=False)
                except BaseException as exc:
                    result = "ABORTED"
                    error = f"Follower disconnect: {type(exc).__name__}: {exc}"
                    print(f"FOLLOWER_DISCONNECT_ERROR {type(exc).__name__}: {exc}", flush=True)
        if leader.bus.is_connected:
            try:
                require_leader_torque_off(leader)
            except BaseException as exc:
                result = "ABORTED"
                error = f"Leader status unverified: {type(exc).__name__}: {exc}"
                print(f"LEADER_STATUS_UNVERIFIED {type(exc).__name__}: {exc}", flush=True)
            finally:
                try:
                    leader.bus.disconnect(disable_torque=False)
                except BaseException as exc:
                    result = "ABORTED"
                    error = f"Leader disconnect: {type(exc).__name__}: {exc}"
                    print(f"LEADER_DISCONNECT_ERROR {type(exc).__name__}: {exc}", flush=True)
        report("stopped" if result == "STOPPED" and hold_ok is True else
               "checked" if result == "CHECK_OK" else "failed")
        print(f"TELEOP_{result} hold_verified={hold_ok}", flush=True)
    return 0 if result == "CHECK_OK" or result == "STOPPED" and hold_ok is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
