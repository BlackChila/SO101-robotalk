#!/usr/bin/env python3
"""Replay one complete recorded SO-101 intro gesture with its original audio."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import select
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from demo_intro_capture import audio_duration, connect_follower, hold_follower
from flux3_joint_frame import NAMES
from flux3_start_pose import CAL_FILE, ROOT, FluxStartController, plan_reset


ACTIVE_TAKE = ROOT / "assets/demo/intro/active.json"


def checked_pose(raw: dict, bounds: dict, label: str) -> dict[str, float]:
    if not isinstance(raw, dict) or set(raw) != set(NAMES):
        raise ValueError(f"{label}: expected six joints")
    pose = {name: float(raw[name]) for name in NAMES}
    for name, value in pose.items():
        low, high = bounds[name]
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{label}: {name} outside calibration")
    return pose


def load_take(path: Path, bounds: dict) -> tuple[dict, list[dict]]:
    report = json.loads(path.read_text())
    if report.get("status") != "recorded":
        raise ValueError("Only a complete recorded take can be replayed")
    if report.get("calibration_sha256") != hashlib.sha256(CAL_FILE.read_bytes()).hexdigest():
        raise ValueError("Follower calibration differs from the recording")
    audio = Path(report["audio"])
    if not audio.is_absolute():
        audio = path.parent / audio
    if not audio.is_file() or hashlib.sha256(audio.read_bytes()).hexdigest() != report.get("audio_sha256"):
        raise ValueError("Recorded audio is missing or has changed")
    if abs(audio_duration(audio) - float(report["audio_duration_s"])) > 0.01:
        raise ValueError("Audio duration changed")
    trajectory = Path(report["trajectory"])
    if not trajectory.is_absolute():
        trajectory = path.parent / trajectory
    if trajectory.resolve().parent not in {
        (ROOT / "outputs/demo-intro").resolve(), ACTIVE_TAKE.parent.resolve(),
    }:
        raise ValueError("Unexpected trajectory directory")
    events = [json.loads(line) for line in trajectory.read_text().splitlines()]
    starts = [event for event in events if event.get("event") == "start"]
    launches = [event for event in events if event.get("event") == "audio_launch"]
    completes = [event for event in events if event.get("event") == "complete"]
    samples = [event for event in events if event.get("event") == "sample"]
    if (len(starts), len(launches), len(completes), len(samples)) != (1, 1, 1, report["sample_count"]):
        raise ValueError("Recording event count is incomplete")
    if any(event.get("event") not in {"start", "sample", "audio_launch", "complete"} for event in events):
        raise ValueError("Recording contains an unexpected event")
    start_pose = checked_pose(report["start_pose"], bounds, "start pose")
    if checked_pose(starts[0]["start_pose"], bounds, "journal start pose") != start_pose:
        raise ValueError("Start pose differs between report and journal")
    total = float(report["planned_duration_s"])
    lead_in = float(report["lead_in_s"])
    duration = float(report["audio_duration_s"])
    fps = float(report["target_fps"])
    if not all(math.isfinite(value) for value in (total, lead_in, duration, fps)):
        raise ValueError("Nonfinite recording timing")
    if not (0 < lead_in < lead_in + duration <= total <= 30 and 20 <= fps <= 60):
        raise ValueError("Invalid recording timing")
    if abs(float(launches[0]["t"]) - lead_in) > 0.05:
        raise ValueError("Audio launch did not match the recorded lead-in")
    if abs(float(completes[0]["t"]) - total) > 0.1:
        raise ValueError("Recording ended at an unexpected time")
    times = [float(event["t"]) for event in samples]
    if not times or times[0] > 0.1 or times[-1] < total - 0.1:
        raise ValueError("Recording does not cover the full sequence")
    if any(not math.isfinite(t) or t < 0 or t >= total for t in times):
        raise ValueError("Invalid sample timestamp")
    if any(current <= previous for previous, current in zip(times, times[1:])):
        raise ValueError("Sample timestamps are not increasing")
    for index, event in enumerate(samples):
        event["target"] = checked_pose(event["target"], bounds, f"sample {index}")
    report["audio"] = str(audio.resolve())
    report["trajectory"] = str(trajectory.resolve())
    return report, samples


def move_to_recorded_start(controller: FluxStartController, start_pose: dict,
                           *, speed_multiplier: float = 2.0, check_interrupt=None) -> dict:
    current = controller.read("Present_Position")
    plan = plan_reset(current, start_pose, controller.bounds,
                      speed_multiplier=speed_multiplier)
    bus = controller.robot.bus
    bus.sync_write("Goal_Position", current)
    if not controller.armed:
        controller.armed = True
        bus.enable_torque(num_retry=1)
    controller.health(expect_torque=1)
    for index, goal in enumerate(plan):
        if check_interrupt is not None:
            check_interrupt()
        tick = time.monotonic()
        bus.sync_write("Goal_Position", goal)
        if index % 10 == 0:
            controller.health(expect_torque=1)
        time.sleep(max(0, 0.05 - (time.monotonic() - tick)))
    time.sleep(0.2)
    controller.health(expect_torque=1)
    return {"from": current, "requested_start": start_pose,
            "measured_start": controller.read("Present_Position"),
            "positioning_duration_s": len(plan) / 20 + 0.2}


def pause_at_start(controller: FluxStartController) -> None:
    print("REPLAY_POSITION_READY: inspect the recorded start pose. "
          "Press Enter to replay, or q to stop while holding position.", flush=True)
    deadline = time.monotonic() + 180
    last_health = 0.0
    while time.monotonic() < deadline:
        if select.select([sys.stdin], [], [], 0.2)[0]:
            command = sys.stdin.readline().strip().lower()
            if command in {"q", "x", "stop"}:
                raise RuntimeError("Operator stopped replay at the start pose")
            if command == "":
                return
        if time.monotonic() - last_health >= 2:
            controller.health(expect_torque=1)
            last_health = time.monotonic()
    raise TimeoutError("No replay start confirmation within 180 seconds")


def establish_measured_hold(controller: FluxStartController) -> dict:
    """Leave every connected exit holding the measured pose with torque on."""
    measured = controller.read("Present_Position")
    controller.robot.bus.sync_write("Goal_Position", measured)
    torque = controller.read("Torque_Enable", normalized=False)
    if set(torque) != set(NAMES):
        raise RuntimeError(f"Incomplete Follower torque state: {torque}")
    if set(torque.values()) == {0}:
        controller.armed = True
        controller.robot.bus.enable_torque(num_retry=1)
    elif set(torque.values()) != {1}:
        raise RuntimeError(f"Mixed Follower torque state: {torque}")
    controller.armed = True
    return hold_follower(controller)


def replay(controller: FluxStartController, take: dict, samples: list[dict], result: dict,
           *, gripper_goal=None, play_audio: bool = True, check_interrupt=None) -> None:
    audio = Path(take["audio"])
    lead_in = float(take["lead_in_s"])
    total = float(take["planned_duration_s"])
    started = time.monotonic()
    player = None
    audio_started = None
    result["started_at_unix"] = time.time()
    observed = []
    try:
        for index, sample in enumerate(samples):
            deadline = started + sample["t"]
            time.sleep(max(0, deadline - time.monotonic()))
            if check_interrupt is not None:
                check_interrupt()
            late = time.monotonic() - deadline
            if late > 0.08:
                raise RuntimeError(f"Replay timing slipped by {late:.3f}s")
            if play_audio and player is None and sample["t"] >= lead_in:
                player = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(audio)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                audio_started = time.monotonic()
                result["audio_launch_offset_s"] = audio_started - started
                print(f"REPLAY_AUDIO_STARTED t={result['audio_launch_offset_s']:.3f}s", flush=True)
            if player is not None and player.poll() is not None and sample["t"] < lead_in + take["audio_duration_s"] - 0.3:
                raise RuntimeError(f"Audio player exited early: {player.returncode}")
            goal = sample["target"].copy()
            if gripper_goal is not None:
                now = time.monotonic()
                elapsed = now - audio_started if audio_started is not None and player.poll() is None else None
                goal["gripper"] = gripper_goal(now, elapsed)
                goal = checked_pose(goal, controller.bounds, "audio-driven intro")
            controller.robot.bus.sync_write("Goal_Position", goal)
            result["executed_samples"] = index + 1
            if index % 5 == 0 or index == len(samples) - 1:
                observed.append({"t": time.monotonic() - started,
                                 "target": goal,
                                 "measured": controller.read("Present_Position")})
            if index % 10 == 0:
                controller.health(expect_torque=1)
        time.sleep(max(0, started + total - time.monotonic()))
        if play_audio and player is None:
            raise RuntimeError("Audio was never started")
        if player is not None:
            player.wait(timeout=1.5)
            if player.returncode:
                raise RuntimeError(f"Audio playback failed: {player.returncode}")
            result["audio_exit_code"] = player.returncode
        result["observed_samples"] = len(observed)
        result["measured_range"] = {
            name: max(row["measured"][name] for row in observed) -
                  min(row["measured"][name] for row in observed)
            for name in NAMES
        }
        result["maximum_tracking_difference"] = {
            name: max(abs(row["target"][name] - row["measured"][name]) for row in observed)
            for name in NAMES
        }
        print(f"REPLAY_MEASURED_RANGE {result['measured_range']}", flush=True)
        result["playback_duration_s"] = time.monotonic() - started
    finally:
        if player is not None and player.poll() is None:
            player.terminate()
            player.wait(timeout=1)
        if player is not None and player.stderr:
            player.stderr.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--take", type=Path, default=ACTIVE_TAKE,
                        help="Complete take report or installed active intro bundle")
    parser.add_argument("--pause-at-start", action="store_true",
                        help="Hold at the recorded start pose until Enter before replay")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt("SIGTERM")))
    controller = FluxStartController()
    take, samples = load_take(args.take, controller.bounds)
    out = ROOT / "outputs/demo-intro" / f"replay-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    result = {"status": "aborted", "source_take": str(args.take.resolve()),
              "sample_count": len(samples), "executed_samples": 0,
              "planned_duration_s": take["planned_duration_s"], "lead_in_s": take["lead_in_s"]}
    try:
        connect_follower(controller)
        print(f"REPLAY_READY samples={len(samples)} duration={take['planned_duration_s']:.3f}s "
              f"audio_at={take['lead_in_s']:.3f}s", flush=True)
        result["positioning"] = move_to_recorded_start(controller, take["start_pose"])
        if args.pause_at_start:
            pause_at_start(controller)
        print("REPLAY_START", flush=True)
        replay(controller, take, samples, result)
        result["status"] = "replayed"
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup_errors = []
        if controller.robot.bus.is_connected:
            try:
                result["hold_position"] = establish_measured_hold(controller)
                result["follower_torque_holding"] = True
            except BaseException as exc:
                result["follower_torque_holding"] = False
                cleanup_errors.append(f"Follower hold unverified: {exc}")
                print("Follower hold could not be verified; support the arm and use the physical power cutoff if needed.", flush=True)
            finally:
                if result.get("follower_torque_holding"):
                    try:
                        controller.robot.bus.disconnect(disable_torque=False)
                    except BaseException as exc:
                        cleanup_errors.append(f"Follower disconnect: {exc}")
        if cleanup_errors:
            result["status"] = "cleanup_failed"
            result["cleanup_error"] = "; ".join(cleanup_errors)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(f"INTRO_REPLAY_{result['status'].upper()} report={out}", flush=True)
    return 0 if result["status"] == "replayed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
