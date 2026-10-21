"""One monitored SO-101 return to the saved start pose from the local UI.

Runs in the shared robot environment. The saved route must have been physically
commissioned before this entry point can write a motor goal. Torque is turned
off and verified when this one-shot request ends or aborts.
"""

from __future__ import annotations

import argparse
import json
import math
import select
import signal
import sys
import time
from pathlib import Path

from flux3_joint_frame import NAMES
from flux3_start_pose import FluxStartController, ROOT


ARM_TRACKING_LIMIT_DEG = 15.0
GRIPPER_TRACKING_LIMIT_PERCENT = 4.0
ARM_GOAL_LEAD_LIMIT_DEG = 10.0
GRIPPER_GOAL_LEAD_LIMIT_PERCENT = 4.0
ARM_SETTLE_LIMIT_DEG = 4.0
GRIPPER_SETTLE_LIMIT_PERCENT = 2.0
RESET_TIMEOUT_SECONDS = 120.0
PROGRESS_CHECK_SECONDS = 3.0
MIN_PROGRESS_DEG = 0.4
MAX_HOLD_SECONDS = 300.0


def require_commissioned(saved: dict) -> None:
    if saved.get("automatic_travel_validated") is not True:
        raise RuntimeError("Automatic movement to the start position has not been validated")


def assert_measured_in_bounds(actual: dict[str, float], bounds: dict) -> None:
    for name in NAMES:
        value = actual[name]
        low, high = bounds[name]
        if not math.isfinite(value) or not low <= value <= high:
            raise RuntimeError(f"Measured start position is outside calibration: {name}={value}")


def assert_tracking(goal: dict[str, float], actual: dict[str, float]) -> None:
    for name in NAMES:
        limit = (GRIPPER_TRACKING_LIMIT_PERCENT if name == "gripper"
                 else ARM_TRACKING_LIMIT_DEG)
        error = abs(goal[name] - actual[name])
        if error > limit:
            raise RuntimeError(
                f"Tracking error {name}: target={goal[name]:.2f}, actual={actual[name]:.2f}, "
                f"deviation={error:.2f} > {limit:.2f}"
            )


def bounded_goal(goal: dict[str, float], actual: dict[str, float]) -> dict[str, float]:
    """Keep a commanded goal close to the measured arm even if a servo lags."""
    result = {}
    for name in NAMES:
        lead = (GRIPPER_GOAL_LEAD_LIMIT_PERCENT if name == "gripper"
                else ARM_GOAL_LEAD_LIMIT_DEG)
        result[name] = max(actual[name] - lead, min(actual[name] + lead, goal[name]))
    return result


def at_start_pose(actual: dict[str, float], target: dict[str, float]) -> bool:
    return all(abs(target[name] - actual[name]) <=
               (GRIPPER_SETTLE_LIMIT_PERCENT if name == "gripper" else ARM_SETTLE_LIMIT_DEG)
               for name in NAMES)


def assert_goal_echo(controller: FluxStartController, goal: dict[str, float]) -> None:
    echoed = controller.read("Goal_Position")
    for name in NAMES:
        limit = 1.0 if name == "gripper" else 0.25
        if abs(echoed[name] - goal[name]) > limit:
            raise RuntimeError(f"Motor goal was not confirmed: {name}")


def move_monitored(controller: FluxStartController, telemetry: list[dict],
                   *, already_holding: bool = False) -> dict:
    controller.health(expect_torque=1 if already_holding else 0)
    start, plan = controller.inspect_plan()
    assert_measured_in_bounds(start, controller.bounds)
    # Keep the current measured pose as the goal before starting or resuming travel.
    controller.robot.bus.sync_write("Goal_Position", start)
    assert_goal_echo(controller, start)
    if not already_holding:
        controller.armed = True
        controller.robot.bus.enable_torque(num_retry=1)
    controller.health(expect_torque=1)

    previous = start
    deadline = time.monotonic() + RESET_TIMEOUT_SECONDS
    progress_at = time.monotonic()
    progress_baseline = start
    index = 0
    while True:
        tick = time.monotonic()
        actual = controller.read("Present_Position")
        assert_tracking(previous, actual)
        if index >= len(plan) and at_start_pose(actual, controller.target):
            return actual
        if tick >= deadline:
            raise RuntimeError(f"The start position was not reached in time: {actual}")
        if tick - progress_at >= PROGRESS_CHECK_SECONDS:
            for name in NAMES:
                if name == "gripper" or abs(controller.target[name] - actual[name]) <= ARM_SETTLE_LIMIT_DEG:
                    continue
                reduction = (abs(controller.target[name] - progress_baseline[name]) -
                             abs(controller.target[name] - actual[name]))
                if reduction < MIN_PROGRESS_DEG:
                    raise RuntimeError(f"No measured movement towards the start position: {name}")
            progress_at = tick
            progress_baseline = actual
        planned = plan[index] if index < len(plan) else controller.target
        goal = bounded_goal(planned, actual)
        for name in NAMES:
            low, high = controller.bounds[name]
            if not low <= goal[name] <= high:
                raise RuntimeError(f"Reset target is outside calibration: {name}={goal[name]}")
        controller.health(expect_torque=1)
        controller.robot.bus.sync_write("Goal_Position", goal)
        assert_goal_echo(controller, goal)
        controller.health(expect_torque=1)
        telemetry.append({"time": time.time(), "target": goal, "actual": actual})
        previous = goal
        index += 1
        time.sleep(max(0.0, 0.05 - (time.monotonic() - tick)))


def hold_until_release(controller: FluxStartController) -> str:
    deadline = time.monotonic() + MAX_HOLD_SECONDS
    while time.monotonic() < deadline:
        controller.health(expect_torque=1)
        actual = controller.read("Present_Position")
        if not at_start_pose(actual, controller.target):
            raise RuntimeError(f"The start position was left during holding: {actual}")
        if select.select([sys.stdin], [], [], 0.2)[0]:
            command = sys.stdin.readline()
            if not command or command.strip().lower() == "r":
                return "operator_release" if command else "api_disconnected"
    return "hold_timeout"


def run(report_path: Path) -> int:
    report = {"outcome": "aborted", "mode": "ui_reset", "telemetry": [],
              "started_at_unix": time.time()}
    controller = None
    try:
        controller = FluxStartController()
        require_commissioned(controller.saved)
        controller.connect()
        report["start"] = controller.read("Present_Position")
        report["target"] = controller.target
        report["measured_after"] = move_monitored(controller, report["telemetry"])
        report["outcome"] = "reset_pose_holding_torque"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print("SO101_UI_RESET_POSE_HOLDING", flush=True)
        report["release_reason"] = hold_until_release(controller)
        report["outcome"] = "released_after_hold"
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if controller is not None:
            try:
                controller.close()
            except BaseException as exc:
                report["outcome"] = "aborted"
                report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        report["ended_at_unix"] = time.time()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"outcome": report["outcome"], "error": report.get("error"),
                          "cleanup_error": report.get("cleanup_error"),
                          "report": str(report_path)}, ensure_ascii=False), flush=True)
    return 0 if report["outcome"] == "released_after_hold" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(run(args.report))


if __name__ == "__main__":
    main()
