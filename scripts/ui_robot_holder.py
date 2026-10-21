"""UI-owned SO-101 reset, live observation and bounded policy action executor.

The process alone owns the follower serial port. Policy workers never open it.
All requests arrive on stdin; every result is written to a unique reply file.
Only an explicit operator torque-off release disables torque. Other exits
hold the measured follower pose with torque enabled before disconnecting.
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

import numpy as np

from flux3_joint_frame import NAMES
from flux3_start_pose import FluxStartController, ROOT
from flux3_ui_reset import (MAX_HOLD_SECONDS, assert_goal_echo,
                            assert_measured_in_bounds, move_monitored,
                            require_commissioned)
from shared_camera_stream import SharedCameraClient


ACTION_RATES = {"molmoact2": 30.0}
MAX_ACTIONS = 32
MAX_TARGET_DELTA = 25.0
MAX_GOAL_LEAD = 10.0
GRIPPER_TORQUE_LIMIT = 300  # 30% of the STS3215's 0-1000 PWM limit.


def _save_reply(path: Path, value: dict) -> None:
    if path.parent != ROOT / "outputs" or not path.name.startswith("ui-robot-reply-"):
        raise ValueError("Invalid reply path")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def _valid_pose(pose: dict) -> dict[str, float]:
    if not isinstance(pose, dict) or set(pose) != set(NAMES):
        raise ValueError("Expected six complete joint channels")
    result = {name: float(pose[name]) for name in NAMES}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("Nonfinite joint value")
    return result


def _owned_path(path: Path, prefix: str) -> Path:
    if path.parent != ROOT / "outputs" or not path.name.startswith(prefix):
        raise ValueError("Invalid controller file path")
    return path


def _epoch_current(path: Path | None, expected: int | None) -> bool:
    if path is None:
        return True
    _owned_path(path, "ui-robot-epoch-")
    try:
        return int(path.read_text()) == expected
    except (OSError, ValueError):
        return False


def _hold_measured(controller: FluxStartController) -> dict[str, float]:
    measured = controller.read("Present_Position")
    assert_measured_in_bounds(measured, controller.bounds)
    controller.robot.bus.sync_write("Goal_Position", measured)
    assert_goal_echo(controller, measured)
    return measured


def _hold_and_disconnect(controller: FluxStartController) -> dict[str, float]:
    measured = _hold_measured(controller)
    controller.health(expect_torque=1)
    controller.robot.bus.disconnect(disable_torque=False)
    return measured


def limit_gripper_torque(controller: FluxStartController) -> None:
    """Cap only the gripper before conversation or MolmoAct2 motion."""
    bus = controller.robot.bus
    current = bus.read("Torque_Limit", "gripper", normalize=False, num_retry=2)
    if current > GRIPPER_TORQUE_LIMIT:
        bus.write("Torque_Limit", "gripper", GRIPPER_TORQUE_LIMIT,
                  normalize=False, num_retry=2)
        current = bus.read("Torque_Limit", "gripper", normalize=False, num_retry=2)
    if not 0 <= current <= GRIPPER_TORQUE_LIMIT:
        raise RuntimeError(f"Gripper torque limit unverified: {current}")


def snapshot(controller: FluxStartController, model_id: str, path: Path) -> dict:
    if model_id not in ACTION_RATES:
        raise ValueError("Unknown policy model")
    if path.parent != ROOT / "outputs" or not path.name.startswith("ui-robot-observation-"):
        raise ValueError("Invalid observation path")
    controller.health(expect_torque=1)
    with SharedCameraClient(model_id) as cameras:
        frames, _ = cameras.fresh(timeout_s=0.8)
        measured = controller.read("Present_Position")
        np.savez(path, **{name: frame[None] for name, frame in frames.items()})
    controller.health(expect_torque=1)
    return {"status": "observed", "model": model_id, "observation_path": str(path),
            "state": measured, "captured_at_unix": time.time()}


def validated_actions(controller: FluxStartController, model_id: str,
                      observed_state: dict, actions: list) -> list[dict[str, float]]:
    if model_id not in ACTION_RATES or not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise ValueError("Invalid policy action block")
    _valid_pose(observed_state)
    checked = []
    previous = None
    for index, raw in enumerate(actions):
        goal = _valid_pose(raw)
        goal["gripper"] = max(0.0, goal["gripper"])
        for name in NAMES:
            low, high = controller.bounds[name]
            if not low <= goal[name] <= high:
                raise RuntimeError(f"Action {index} outside calibration: {name}")
            if previous is not None and abs(goal[name] - previous[name]) > MAX_TARGET_DELTA:
                raise RuntimeError(f"Action {index} exceeds 25-unit step: {name}")
        checked.append(goal)
        previous = goal
    return checked


def execute_actions(controller: FluxStartController, model_id: str, observed_state: dict,
                    actions: list, *, epoch_path: Path | None = None,
                    epoch: int | None = None, listen_for_release: bool = True) -> dict:
    controller.health(expect_torque=1)
    if model_id == "molmoact2":
        limit_gripper_torque(controller)
    checked = validated_actions(controller, model_id, observed_state, actions)
    rate = ACTION_RATES[model_id]
    trace = []
    for index, target in enumerate(checked):
        tick = time.monotonic()
        if not _epoch_current(epoch_path, epoch):
            measured = _hold_measured(controller)
            return {"status": "stopped", "executedActions": index,
                    "measured_after": measured}
        if listen_for_release and select.select([sys.stdin], [], [], 0)[0]:
            if sys.stdin.readline().strip().lower() == "r":
                return {"status": "release_requested", "executedActions": index}
        controller.health(expect_torque=1)
        actual = controller.read("Present_Position")
        assert_measured_in_bounds(actual, controller.bounds)
        goal = {name: actual[name] + max(-MAX_GOAL_LEAD, min(MAX_GOAL_LEAD,
                target[name] - actual[name])) for name in NAMES}
        controller.robot.bus.sync_write("Goal_Position", goal)
        assert_goal_echo(controller, goal)
        trace.append({"index": index, "time": time.time(), "actual": actual, "goal": goal})
        time.sleep(max(0.0, 1 / rate - (time.monotonic() - tick)))
    controller.health(expect_torque=1)
    # Hold at the boundary until the next fresh observation and action block.
    measured = _hold_measured(controller)
    return {"status": "executed", "model": model_id, "executedActions": len(trace),
            "measured_after": measured, "trace": trace}


def command_loop(controller: FluxStartController, report: dict, report_path: Path) -> str:
    idle_deadline = time.monotonic() + MAX_HOLD_SECONDS
    task_active = False
    while task_active or time.monotonic() < idle_deadline:
        controller.health(expect_torque=1)
        assert_measured_in_bounds(controller.read("Present_Position"), controller.bounds)
        if not select.select([sys.stdin], [], [], 0.2)[0]:
            continue
        line = sys.stdin.readline()
        if not line or line.strip().lower() == "r":
            return "operator_release" if line else "api_disconnected"
        command = json.loads(line)
        reply_path = Path(command["reply_path"])
        try:
            if command.get("op") == "task_active":
                task_active = True
                response = {"status": "task_active"}
            elif command.get("op") == "task_inactive":
                task_active = False
                response = {"status": "task_inactive"}
            elif command.get("op") == "snapshot":
                if not task_active:
                    raise RuntimeError("No active physical task")
                response = snapshot(controller, command["model"], Path(command["observation_path"]))
            elif command.get("op") == "return_to_start":
                if task_active:
                    raise RuntimeError("Zuerst die laufende Aufgabe stoppen.")
                require_commissioned(controller.saved)
                move_monitored(controller, report["telemetry"], already_holding=True)
                measured = _hold_measured(controller)
                response = {"status": "returned", "measured_after": measured}
                report["last_return"] = response
                report_path.write_text(json.dumps(report, indent=2) + "\n")
            elif command.get("op") == "execute":
                if not task_active:
                    raise RuntimeError("No active physical task")
                actions_path = _owned_path(Path(command["actions_path"]), "ui-robot-actions-")
                actions = json.loads(actions_path.read_text())
                response = execute_actions(controller, command["model"],
                                           command["observed_state"], actions,
                                           epoch_path=Path(command["epoch_path"]),
                                           epoch=command["epoch"])
                if response["status"] == "release_requested":
                    _save_reply(reply_path, response)
                    return "operator_release"
                report["last_execution"] = {key: value for key, value in response.items() if key != "trace"}
                report_path.write_text(json.dumps(report, indent=2) + "\n")
            else:
                raise ValueError("Unsupported controller operation")
            _save_reply(reply_path, response)
            idle_deadline = time.monotonic() + MAX_HOLD_SECONDS
        except Exception as exc:
            # A rejected block leaves the last verified goal in place. A
            # partial block is frozen at the measured pose before another task.
            controller.health(expect_torque=1)
            measured = controller.read("Present_Position")
            assert_measured_in_bounds(measured, controller.bounds)
            controller.robot.bus.sync_write("Goal_Position", measured)
            assert_goal_echo(controller, measured)
            _save_reply(reply_path, {"status": "rejected", "error": f"{type(exc).__name__}: {exc}"})
    return "hold_timeout"


def run(report_path: Path) -> int:
    report = {"outcome": "aborted", "mode": "ui_robot_holder", "telemetry": [],
              "capabilities": ["return_to_start"], "started_at_unix": time.time()}
    controller = None
    release_reason = None
    try:
        controller = FluxStartController()
        require_commissioned(controller.saved)
        controller.connect()
        report["start"] = controller.read("Present_Position")
        report["target"] = controller.target
        report["measured_after"] = move_monitored(controller, report["telemetry"])
        report["outcome"] = "reset_pose_holding_torque"
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print("SO101_UI_RESET_POSE_HOLDING", flush=True)
        release_reason = command_loop(controller, report, report_path)
        report["release_reason"] = release_reason
        report["outcome"] = ("released_after_hold" if release_reason == "operator_release"
                             else "holding_after_disconnect")
    except BaseException as exc:
        report["outcome"] = "aborted"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if controller is not None:
            try:
                if release_reason == "operator_release":
                    controller.close()
                elif controller.robot.bus.is_connected and controller.armed:
                    report["measured_at_disconnect"] = _hold_and_disconnect(controller)
                    report["follower_torque_holding"] = True
                elif controller.robot.bus.is_connected:
                    controller.robot.bus.disconnect(disable_torque=False)
            except BaseException as exc:
                report["outcome"] = "aborted"
                action = ("Drehmoment aus" if release_reason == "operator_release"
                          else "Halteziel oder Drehmoment")
                report["cleanup_error"] = f"{action} nicht verifizierbar: {type(exc).__name__}: {exc}"
        report["ended_at_unix"] = time.time()
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["outcome"] == "released_after_hold" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(run(args.report))


if __name__ == "__main__":
    main()
