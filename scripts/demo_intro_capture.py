#!/usr/bin/env python3
"""Capture one supervised Leader-to-Follower intro gesture with timed audio.

The recording is a joint trajectory, not a LeRobot training episode. The
Follower first follows the Leader live; the operator then arms a take with r,
and the next deliberate Leader movement starts its timeline. This tool never
replays a saved trajectory or starts a policy worker.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import select
import subprocess
import sys
import termios
import time
from datetime import datetime, timezone
from pathlib import Path


from flux3_joint_frame import NAMES
from flux3_start_pose import FluxStartController, ROOT, plan_reset


LEADER_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B41533008-if00"
LEADER_CALIBRATION = Path("/home/dfin/projects/SO101/calibration/teleoperators/so_leader")
MAX_TICK_LATE = 0.08


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        check=True, text=True, capture_output=True,
    )
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0 or duration > 30:
        raise ValueError(f"Unsupported audio duration: {duration}")
    return duration


def require_leader_torque_off(leader: SO101Leader) -> None:
    torque = leader.bus.sync_read("Torque_Enable", normalize=False, num_retry=5)
    if set(torque) != set(NAMES) or any(torque.values()):
        raise RuntimeError(f"Leader torque must be off: {torque}")


def initial_alignment(controller: FluxStartController, leader: SO101Leader) -> tuple[dict, dict]:
    measured = controller.read("Present_Position")
    action = leader.get_action()
    if set(action) != {f"{name}.pos" for name in NAMES}:
        raise RuntimeError("Leader returned incomplete joint data")
    errors = {name: float(action[f"{name}.pos"]) - measured[name] for name in NAMES}
    if not all(math.isfinite(error) for error in errors.values()):
        raise RuntimeError("Leader returned a nonfinite joint position")
    return measured, errors


def checked_action(controller: FluxStartController, leader_action: dict) -> dict:
    if set(leader_action) != {f"{name}.pos" for name in NAMES}:
        raise RuntimeError("Leader returned incomplete joint data")
    target = {}
    for name in NAMES:
        value = float(leader_action[f"{name}.pos"])
        low, high = controller.bounds[name]
        if not math.isfinite(value) or not low <= value <= high:
            raise RuntimeError(f"Leader goal outside follower calibration: {name}={value}")
        target[name] = value
    return target


def connect_follower(controller: FluxStartController) -> None:
    """Accept either an unpowered arm or one left holding by a previous take."""
    bus = controller.robot.bus
    bus.connect()
    fcntl.ioctl(bus.port_handler.ser.fileno(), termios.TIOCEXCL)
    if not bus.is_calibrated:
        raise RuntimeError("Follower calibration mismatch")
    torque = controller.read("Torque_Enable", normalized=False)
    if set(torque.values()) == {1}:
        controller.armed = True
        controller.health(expect_torque=1)
    elif set(torque.values()) == {0}:
        controller.health(expect_torque=0)
    else:
        raise RuntimeError(f"Mixed Follower torque state: {torque}")


def hold_follower(controller: FluxStartController) -> dict:
    """Freeze at the measured pose and verify that every motor still holds."""
    measured = controller.read("Present_Position")
    controller.robot.bus.sync_write("Goal_Position", measured)
    echoed = controller.read("Goal_Position")
    for name in NAMES:
        tolerance = 1.0 if name == "gripper" else 0.25
        if abs(echoed[name] - measured[name]) > tolerance:
            raise RuntimeError(f"Follower hold goal not confirmed: {name}")
    # Temperature limits stop motion, but measured-goal and torque verification
    # determine whether the stationary Follower is holding its pose.
    controller.health(expect_torque=1, check_temperature=False)
    return measured


def prepare_leader_start(controller: FluxStartController, leader: SO101Leader) -> dict:
    """Move slowly to the Leader's current pose before the recorded timeline."""
    current = controller.read("Present_Position")
    target = checked_action(controller, leader.get_action())
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
    measured = controller.read("Present_Position")
    return {"from": current, "leader_start": target, "measured_start": measured,
            "duration_s": len(plan) / 20 + 0.4}


def wait_for_operator(controller: FluxStartController, leader: SO101Leader,
                      report: dict, fps: float, total: float) -> None:
    """Follow the Leader live; arm with r, then start recording on actual motion."""
    if not controller.armed:
        raise RuntimeError("The Follower must be prepared and holding before live teleoperation")
    print("INTRO_TELEOP_ACTIVE: move the Leader and verify the Follower follows. "
          f"Press r to arm recording, then move the Leader to start the {total:g}-second take; "
          "press q to stop without recording.", flush=True)
    started = time.monotonic()
    next_tick = started
    baseline = None
    target_min = {}
    target_max = {}
    measured_min = {}
    measured_max = {}
    rehearsal = {"samples": 0, "armed": False}
    report["rehearsal"] = rehearsal
    while time.monotonic() - started < 300:
        command = None
        if select.select([sys.stdin], [], [], 0)[0]:
            line = sys.stdin.readline()
            if not line or line.strip().lower() in {"q", "x", "stop"}:
                raise RuntimeError("Operator stopped live teleoperation")
            command = line.strip().lower()
        measured = controller.read("Present_Position")
        target = checked_action(controller, leader.get_action())
        controller.robot.bus.sync_write("Goal_Position", target)
        rehearsal["samples"] += 1
        for name in NAMES:
            target_min[name] = min(target_min.get(name, target[name]), target[name])
            target_max[name] = max(target_max.get(name, target[name]), target[name])
            measured_min[name] = min(measured_min.get(name, measured[name]), measured[name])
            measured_max[name] = max(measured_max.get(name, measured[name]), measured[name])
        rehearsal["target_range"] = {name: target_max[name] - target_min[name] for name in NAMES}
        rehearsal["measured_range"] = {name: measured_max[name] - measured_min[name] for name in NAMES}
        if command == "r":
            baseline = target.copy()
            rehearsal["armed"] = True
            print("INTRO_RECORD_ARMED: continue moving the Leader; recording starts on the next "
                  "2-degree (or gripper-unit) movement.", flush=True)
        elif baseline is not None and max(abs(target[name] - baseline[name]) for name in NAMES) >= 2:
            rehearsal["duration_s"] = time.monotonic() - started
            report["record_trigger"] = {"reason": "leader_motion", "baseline": baseline,
                                        "target": target}
            print("INTRO_RECORD_TRIGGERED: 4 seconds of teleoperation, then audio, "
                  "then the final pose.", flush=True)
            return
        if rehearsal["samples"] % 10 == 0:
            controller.health(expect_torque=1)
        if rehearsal["samples"] % (int(fps) * 5) == 0:
            print(f"INTRO_TELEOP_TRACE target_range={rehearsal['target_range']} "
                  f"measured_range={rehearsal['measured_range']}", flush=True)
        next_tick += 1 / fps
        sleep = next_tick - time.monotonic()
        if sleep < -MAX_TICK_LATE:
            raise RuntimeError(f"Live teleoperation loop missed timing by {-sleep:.3f}s")
        if sleep > 0:
            time.sleep(sleep)
    raise TimeoutError("Live teleoperation timed out before recording was triggered")


def capture(controller: FluxStartController, leader: SO101Leader, *, audio: Path,
            lead_in: float, duration: float, total: float, fps: float, report: dict, journal) -> None:
    controller.health(expect_torque=1 if controller.armed else 0)
    require_leader_torque_off(leader)
    start_pose, errors = initial_alignment(controller, leader)
    report["start_pose"] = start_pose
    report["alignment_error"] = errors
    report["sample_count"] = 0
    journal.write(json.dumps({"event": "start", "start_pose": start_pose,
                              "alignment_error": errors}) + "\n")
    journal.flush()
    if not controller.armed:
        controller.robot.bus.sync_write("Goal_Position", start_pose)
        controller.armed = True
        controller.robot.bus.enable_torque(num_retry=1)
    controller.health(expect_torque=1)
    print(f"START: move the Leader now. Audio begins after {lead_in:.2f} seconds.", flush=True)
    started = time.monotonic()
    report["started_at_unix"] = time.time()
    next_tick = started
    player = None
    audio_started = None
    audio_end_cued = False
    index = 0
    try:
        while True:
            now = time.monotonic()
            elapsed = now - started
            if elapsed >= total:
                break
            if select.select([sys.stdin], [], [], 0)[0]:
                command = sys.stdin.readline().strip().lower()
                if command in {"x", "q", "stop"}:
                    raise RuntimeError("Operator stopped the take")
            if player is None and elapsed >= lead_in:
                player = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(audio)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                audio_started = time.monotonic() - started
                report["audio_launch_offset_s"] = audio_started
                journal.write(json.dumps({"event": "audio_launch", "t": audio_started}) + "\n")
                journal.flush()
                print(f"AUDIO_STARTED t={audio_started:.3f}s", flush=True)
            if not audio_end_cued and elapsed >= lead_in + duration:
                audio_end_cued = True
                report["audio_end_cue_offset_s"] = time.monotonic() - started
                print("AUDIO_DONE: move the Leader to the final viewing pose now.", flush=True)
            if player is not None and player.poll() is not None and elapsed < lead_in + duration - 0.3:
                raise RuntimeError(f"Audio player exited early: {player.returncode}")
            measured = controller.read("Present_Position")
            leader_action = leader.get_action()
            try:
                target = checked_action(controller, leader_action)
            except Exception:
                journal.write(json.dumps({"event": "rejected_action", "t": time.monotonic() - started,
                                          "leader": leader_action, "measured": measured}) + "\n")
                journal.flush()
                raise
            controller.robot.bus.sync_write("Goal_Position", target)
            journal.write(json.dumps({"event": "sample", "t": time.monotonic() - started,
                                      "target": target, "measured": measured}) + "\n")
            journal.flush()
            report["sample_count"] += 1
            index += 1
            if index % 10 == 0:
                controller.health(expect_torque=1)
            next_tick += 1 / fps
            sleep = next_tick - time.monotonic()
            if sleep < -MAX_TICK_LATE:
                raise RuntimeError(f"Teleoperation loop missed timing by {-sleep:.3f}s")
            if sleep > 0:
                time.sleep(sleep)
        if player is None:
            raise RuntimeError("Audio never started")
        try:
            player.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Audio playback exceeded the timed take")
        if player.returncode:
            raise RuntimeError(f"Audio playback failed: {player.returncode}")
    finally:
        if player is not None and player.poll() is None:
            player.terminate()
            player.wait(timeout=1)
        if player is not None and player.stderr:
            player.stderr.close()
    report["duration_s"] = time.monotonic() - started
    report["final_measured"] = controller.read("Present_Position")
    journal.write(json.dumps({"event": "complete", "t": report["duration_s"],
                              "final_measured": report["final_measured"]}) + "\n")
    journal.flush()


def main() -> int:
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--lead-in-s", type=float, default=4.0)
    parser.add_argument("--total-s", type=float, default=11.0)
    parser.add_argument("--prepare-start", action="store_true",
                        help="Slowly align the Follower before live teleoperation and recording")
    parser.add_argument("--fps", type=float, default=50.0)
    args = parser.parse_args()
    if not args.audio.is_file() or args.lead_in_s != 4.0 or not 20 <= args.fps <= 60:
        parser.error("Expected an existing audio file, a 4-second lead-in, and 20-60 fps")
    if not args.prepare_start:
        parser.error("Use --prepare-start so the Follower is aligned before live teleoperation")
    duration = audio_duration(args.audio)
    if not math.isfinite(args.total_s) or not args.lead_in_s + duration <= args.total_s <= 30:
        parser.error("Total duration must include the 4-second lead-in and complete audio")
    out = ROOT / "outputs/demo-intro" / f"take-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    journal_path = out.with_suffix(".jsonl")
    report = {"status": "aborted", "audio": str(args.audio.resolve()),
              "trajectory": str(journal_path),
              "audio_sha256": hashlib.sha256(args.audio.read_bytes()).hexdigest(),
              "audio_duration_s": duration, "lead_in_s": args.lead_in_s,
              "planned_duration_s": args.total_s, "target_fps": args.fps,
              "calibration_sha256": hashlib.sha256(Path(controller_calibration_path()).read_bytes()).hexdigest()}
    controller = FluxStartController()
    leader = SO101Leader(SO101LeaderConfig(
        port=LEADER_PORT, id="leader_main", calibration_dir=LEADER_CALIBRATION,
        use_degrees=True, num_read_retries=5,
    ))
    try:
        connect_follower(controller)
        leader.bus.connect()
        fcntl.ioctl(leader.bus.port_handler.ser.fileno(), termios.TIOCEXCL)
        if not leader.is_calibrated:
            raise RuntimeError("Leader calibration mismatch")
        require_leader_torque_off(leader)
        initial, errors = initial_alignment(controller, leader)
        print(f"PREFLIGHT_OK initial={initial} alignment_error={errors} total={args.total_s:.3f}s", flush=True)
        report["preparation"] = prepare_leader_start(controller, leader)
        print(f"PREPARE_DONE measured={report['preparation']['measured_start']}", flush=True)
        wait_for_operator(controller, leader, report, args.fps, args.total_s)
        out.parent.mkdir(parents=True, exist_ok=True)
        with journal_path.open("w") as journal:
            capture(controller, leader, audio=args.audio, lead_in=args.lead_in_s,
                    duration=duration, total=args.total_s, fps=args.fps, report=report, journal=journal)
        report["status"] = "recorded"
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup_errors = []
        if controller.robot.bus.is_connected:
            try:
                if controller.armed:
                    report["hold_position"] = hold_follower(controller)
                    report["follower_torque_holding"] = True
            except BaseException as exc:
                report["follower_torque_holding"] = False
                cleanup_errors.append(f"Follower hold unverified: {exc}")
            finally:
                try:
                    controller.robot.bus.disconnect(disable_torque=False)
                except BaseException as exc:
                    cleanup_errors.append(f"Follower disconnect: {exc}")
        if leader.bus.is_connected:
            try:
                leader.bus.disable_torque(num_retry=5)
                require_leader_torque_off(leader)
            except BaseException as exc:
                cleanup_errors.append(f"Leader: {exc}")
            finally:
                leader.bus.disconnect(disable_torque=False)
        if cleanup_errors:
            report["status"] = "cleanup_failed"
            report["cleanup_error"] = "; ".join(cleanup_errors)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(f"INTRO_CAPTURE_{report['status'].upper()} report={out}", flush=True)
        if cleanup_errors:
            print("Follower hold could not be verified; support the arm and use the physical power cutoff if needed.", flush=True)
    return 0 if report["status"] == "recorded" else 1


def controller_calibration_path() -> str:
    return "/home/dfin/projects/SO101/calibration/robots/so_follower/follower_main.json"


if __name__ == "__main__":
    raise SystemExit(main())
