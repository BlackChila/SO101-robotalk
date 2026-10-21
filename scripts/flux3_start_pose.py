"""Shared SO-101 measured-position controller for conversation and teleoperation.

Default invocation is read-only. ``--move`` is a supervised hardware operation.
The historical module/class names are retained for installation compatibility.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import signal
import termios
import time
from pathlib import Path


from flux3_joint_frame import NAMES

ROOT = Path(__file__).resolve().parents[1]
POSE_FILE = ROOT / "config/flux3_start_pose.json"
CAL_FILE = Path("/home/dfin/projects/SO101/calibration/robots/so_follower/follower_main.json")


def calibrated_bounds(calibration: dict) -> dict[str, tuple[float, float]]:
    result = {}
    for name in NAMES:
        if name == "gripper":
            result[name] = (0.0, 100.0)
        else:
            item = calibration[name]
            half = (item["range_max"] - item["range_min"]) * 180 / 4095
            result[name] = (-half, half)
    return result


def plan_reset(start: dict[str, float], target: dict[str, float],
               bounds: dict[str, tuple[float, float]],
               *, allow_large_travel: bool = False,
               speed_multiplier: float = 2.0) -> list[dict[str, float]]:
    if not math.isfinite(speed_multiplier) or not 0 < speed_multiplier <= 4.0:
        raise ValueError("Reset speed multiplier must be in (0, 4]")
    if any(set(d) != set(NAMES) for d in (start, target, bounds)):
        raise ValueError("Expected exactly six SO101 channels")
    bounded_start = {}
    for name in NAMES:
        if not all(math.isfinite(v) for v in (start[name], target[name], *bounds[name])):
            raise ValueError(f"Nonfinite {name}")
        low, high = bounds[name]
        if not low <= target[name] <= high:
            raise ValueError(f"{name} target outside calibration: {target[name]}, {bounds[name]}")
        bounded_start[name] = min(max(start[name], low), high)
    # Base rates 4 deg/s arm, 5 percent/s gripper, nominal 20 Hz.
    # Default multiplier 2 gives 8 deg/s; conversation multiplier 4 gives 16.
    seconds = max(max(abs(target[n] - bounded_start[n]) /
                      ((5.0 if n == "gripper" else 4.0) * speed_multiplier)
                      for n in NAMES), 0.05)
    steps = max(1, math.ceil(seconds * 20))
    return [{n: bounded_start[n] + (target[n] - bounded_start[n]) * i / steps for n in NAMES}
            for i in range(1, steps + 1)]


class FluxStartController:
    def __init__(self, pose_file: Path = POSE_FILE, *, temperature_limit_c: int = 45):
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

        if not 45 <= temperature_limit_c <= 60:
            raise ValueError("Temperature limit must be between 45 and 60 C")
        self.temperature_limit_c = temperature_limit_c
        self.saved = json.loads(pose_file.read_text())
        self.calibration = json.loads(CAL_FILE.read_text())
        if self.saved["calibration_sha256"] != hashlib.sha256(CAL_FILE.read_bytes()).hexdigest():
            raise RuntimeError("Saved pose belongs to a different follower calibration")
        if self.saved["robot_id"] != "follower_main":
            raise RuntimeError("Saved pose belongs to another robot")
        self.bounds = calibrated_bounds(self.calibration)
        self.target = self.saved["measured_position"]
        self.robot = SO101Follower(SO101FollowerConfig(
            port=self.saved["port"], id="follower_main", use_degrees=True,
            calibration_dir=CAL_FILE.parent, cameras={}, max_relative_target=None,
        ))
        self.armed = False
        self.temperature_spikes: list[dict] = []

    def connect(self, *, holding: bool = False):
        self.robot.bus.connect()
        fcntl.ioctl(self.robot.bus.port_handler.ser.fileno(), termios.TIOCEXCL)
        if not self.robot.bus.is_calibrated:
            raise RuntimeError("Follower calibration mismatch")
        self.health(expect_torque=1 if holding else 0)
        if holding:
            self.armed = True

    def read(self, register: str, *, normalized: bool = True) -> dict:
        values = self.robot.bus.sync_read(register, normalize=normalized, num_retry=2)
        if set(values) != set(NAMES) or not all(math.isfinite(v) for v in values.values()):
            raise RuntimeError(f"Incomplete {register}: {values}")
        return values

    def health(self, *, expect_torque: int, check_temperature: bool = True):
        torque = self.read("Torque_Enable", normalized=False)
        status = self.read("Status", normalized=False)
        mode = self.read("Operating_Mode", normalized=False)
        temp = self.read("Present_Temperature", normalized=False)
        if set(torque.values()) != {expect_torque} or any(status.values()) or any(mode.values()):
            raise RuntimeError(f"Motor health: torque={torque}, status={status}, mode={mode}, temp={temp}")
        if not check_temperature:
            return
        temperature_limit_c = getattr(self, "temperature_limit_c", 45)
        high_names = {name for name, value in temp.items() if value >= temperature_limit_c}
        if high_names:
            initial_high_names = high_names.copy()
            samples = [temp]
            start = time.monotonic()
            def log_sample(values: dict, elapsed: float) -> None:
                print("MOTOR_TEMPERATURE_SAMPLE " + json.dumps({
                    "time_unix": time.time(), "elapsed_seconds": round(elapsed, 3),
                    "temperatures_c": values, "threshold_c": temperature_limit_c,
                }, separators=(",", ":")), flush=True)

            log_sample(temp, 0.0)
            while time.monotonic() - start < 1.0:
                time.sleep(0.05)
                repeat = self.read("Present_Temperature", normalized=False)
                samples.append(repeat)
                elapsed = time.monotonic() - start
                log_sample(repeat, elapsed)
                high_names = {name for name in high_names if repeat[name] >= temperature_limit_c}
                if not high_names:
                    self.temperature_spikes.append({"time": time.time(),
                                                    "duration_seconds": elapsed,
                                                    "samples": samples})
                    print("MOTOR_TEMPERATURE_EVENT " + json.dumps({
                        "outcome": "normalized", "observed_seconds": round(elapsed, 3),
                        "sample_count": len(samples),
                        "initial_hot_motors": sorted(initial_high_names),
                        "peak_c": {name: max(sample[name] for sample in samples)
                                   for name in sorted(initial_high_names)},
                    }, separators=(",", ":")), flush=True)
                    print(f"FLUX3_TRANSIENT_TEMPERATURE_NORMALIZED_AFTER_{elapsed:.2f}s", flush=True)
                    return
            observed = time.monotonic() - start
            peak = {name: max(sample[name] for sample in samples) for name in sorted(high_names)}
            print("MOTOR_TEMPERATURE_EVENT " + json.dumps({
                "outcome": "threshold", "observed_seconds": round(observed, 3),
                "sample_count": len(samples), "persistent_motors": sorted(high_names),
                "peak_c": peak,
            }, separators=(",", ":")), flush=True)
            raise RuntimeError(f"Motor temperature remained >={temperature_limit_c} C for at least 1 s: "
                               f"motors={sorted(high_names)}, observed_s={observed:.2f}, "
                               f"peak_c={peak}, first={temp}, last={samples[-1]}")

    def inspect_plan(self, *, allow_large_travel: bool = False) -> tuple[dict, list[dict]]:
        start = self.read("Present_Position")
        return start, plan_reset(start, self.target, self.bounds,
                                 allow_large_travel=allow_large_travel)

    def move_to_start(self, telemetry: list[dict] | None = None,
                      *, commission_travel: bool = False,
                      already_holding: bool = False,
                      allow_large_travel: bool = False) -> list[dict]:
        self.health(expect_torque=1 if already_holding else 0)
        start, plan = self.inspect_plan(allow_large_travel=allow_large_travel)
        bounded_start = {name: min(max(start[name], self.bounds[name][0]), self.bounds[name][1])
                         for name in NAMES}
        self.robot.bus.sync_write("Goal_Position", bounded_start)
        if not already_holding:
            self.armed = True  # Ensure cleanup after a partial torque enable.
            self.robot.bus.enable_torque(num_retry=1)
        self.health(expect_torque=1)
        if telemetry is None:
            telemetry = []
        for goal in plan:
            tick = time.monotonic()
            actual = self.read("Present_Position")
            for name in NAMES:
                if not self.bounds[name][0] <= goal[name] <= self.bounds[name][1]:
                    raise RuntimeError(f"Reset goal outside calibration: {name}={goal[name]}")
            self.robot.bus.sync_write("Goal_Position", goal)
            self.health(expect_torque=1)
            telemetry.append({"time": time.time(), "target": goal, "actual": actual,
                              "phase": "calibration_bounded_reset"})
            time.sleep(max(0, 0.05 - (time.monotonic() - tick)))
        return telemetry

    def close(self):
        if not self.robot.bus.is_connected:
            return
        try:
            if self.armed:
                self.robot.bus.disable_torque(num_retry=3)
                torque = self.read("Torque_Enable", normalized=False)
                if any(torque.values()):
                    raise RuntimeError(f"Torque-off readback failed: {torque}; use power cutoff")
                self.armed = False
        finally:
            self.robot.bus.disconnect(disable_torque=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--move", action="store_true", help="Supervised physical reset; default only prints plan")
    parser.add_argument("--hold-seconds", type=float,
                        help="Optional diagnostic hold duration; default holds until Ctrl+C")
    args = parser.parse_args()
    if args.hold_seconds is not None and not 0 <= args.hold_seconds <= 30:
        parser.error("--hold-seconds must be in [0,30]")
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    controller = FluxStartController()
    telemetry = []
    outcome = "read_only_plan"
    try:
        controller.connect()
        start, plan = controller.inspect_plan()
        print(json.dumps({"mode": "move" if args.move else "read_only_plan",
                          "start": start, "saved_start_pose": controller.target,
                          "steps": len(plan), "last_command": plan[-1]}, indent=2), flush=True)
        if args.move:
            outcome = "aborted"
            controller.move_to_start(telemetry)
            outcome = "reached_saved_start_pose"
            print("FLUX3_START_POSE_TORQUE_HOLD_ENGAGED", flush=True)
            deadline = None if args.hold_seconds is None else time.monotonic() + args.hold_seconds
            while deadline is None or time.monotonic() < deadline:
                controller.health(expect_torque=1)
                actual = controller.read("Present_Position")
                telemetry.append({"time": time.time(), "phase": "hold",
                                  "target": controller.target, "actual": actual})
                time.sleep(0.1)
    except BaseException as exc:
        outcome = f"aborted: {type(exc).__name__}: {exc}"
    finally:
        try:
            controller.close()
        except BaseException as exc:
            outcome += f"; CLOSE ERROR: {exc}"
        out = ROOT / "outputs/flux3-start-pose-reset-last.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"outcome": outcome, "telemetry": telemetry}, indent=2) + "\n")
        print(outcome, flush=True)
    if outcome.startswith("aborted"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
