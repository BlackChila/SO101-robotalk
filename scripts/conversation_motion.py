#!/usr/bin/env python3
"""Own the Follower during one voice call: intro replay, final hold, speech gripper."""

from __future__ import annotations

import argparse
import json
import math
import os
import select
import signal
import sys
import time
from pathlib import Path

from demo_intro_capture import connect_follower
from demo_intro_replay import (ACTIVE_TAKE, establish_measured_hold, load_take,
                               move_to_recorded_start, replay)
from flux3_start_pose import FluxStartController
from face_tracking_control import FaceTrackingController
from conversation_head_tilt import HeadTiltAnimator
from intro_speech_envelope import IntroSpeechEnvelope
from flux3_ui_reset import assert_goal_echo
from ui_robot_holder import (_owned_path, _save_reply, execute_actions,
                             limit_gripper_torque, snapshot)

RATE_HZ = 50
CONVERSATION_POSITIONING_SPEED = 4.0
CONVERSATION_TEMPERATURE_LIMIT_C = 60
# Increase speech travel and the opening cap by 30%; retain motor speed limits.
SPEECH_TRAVEL_FRACTION = 0.234
OPEN_SPEED = 60.0  # Calibrated gripper percentage points per second.
CLOSE_SPEED = 75.0
PLAYBACK_TIMEOUT_S = 0.3
HEARTBEAT_TIMEOUT_S = 20.0


def write_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


class SpeechGripperAnimator:
    """Continuously follow the audible speech envelope; never invent a cycle."""

    def __init__(self, rest: dict, bounds: dict):
        self.rest = rest.copy()
        low, high = bounds["gripper"]
        if (not all(math.isfinite(v) for v in (low, high, rest["gripper"]))
                or not low <= rest["gripper"] < low + (high - low) * 0.15):
            raise ValueError("Recorded gripper rest must be below the speaking-open range")
        self.open_high = min(low + (high - low) * 0.26,
                             rest["gripper"] + (high - low) * SPEECH_TRAVEL_FRACTION)
        self.current = float(rest["gripper"])
        self.bounds = (low, high)
        self.last_tick: float | None = None

    def rebase(self, measured: dict, now: float) -> None:
        """Resume from a measured hold without redefining the neutral mouth."""
        current = measured["gripper"]
        if (not math.isfinite(now) or not math.isfinite(current)
                or not self.bounds[0] <= current <= self.bounds[1]):
            raise ValueError("Invalid measured speech-gripper hold")
        self.rest.update({name: value for name, value in measured.items() if name != "gripper"})
        self.current = float(current)
        self.last_tick = now

    def goal(self, now: float, level: float | None) -> dict:
        if not math.isfinite(now):
            raise ValueError("Nonfinite gripper time")
        if level is not None and (not math.isfinite(level) or not 0 <= level <= 1):
            raise ValueError("Invalid audio level")
        dt = 1 / RATE_HZ if self.last_tick is None else max(0, min(now - self.last_tick, 1 / RATE_HZ))
        self.last_tick = now
        target = self.rest["gripper"] + (self.open_high - self.rest["gripper"]) * (level or 0.0)
        delta = target - self.current
        step = (OPEN_SPEED if delta > 0 else CLOSE_SPEED) * dt
        self.current += max(-step, min(step, delta))
        goal = self.rest.copy()
        goal["gripper"] = self.current
        return goal


def prepare_intro_gripper(take: dict, bounds: dict):
    """Decode before connecting; replay supplies time since audio player launch."""
    envelope = IntroSpeechEnvelope.from_file(Path(take["audio"]))
    animator = SpeechGripperAnimator(take["start_pose"], bounds)

    def goal(now: float, audio_elapsed: float | None) -> float:
        return animator.goal(now, envelope.level_at(audio_elapsed))["gripper"]

    return goal


class MotionCommandReader:
    """Read every complete pipe line without TextIOWrapper/select read-ahead stalls."""

    def __init__(self, fd: int):
        self.fd = fd
        self.pending = b""
        self.eof = False

    def poll(self) -> list[dict]:
        if not select.select([self.fd], [], [], 0)[0]:
            return []
        chunk = os.read(self.fd, 65536)
        if not chunk:
            self.eof = True
            if self.pending:
                raise ValueError("Incomplete motion command at disconnect")
            return []
        self.pending += chunk
        lines = self.pending.split(b"\n")
        self.pending = lines.pop()
        if len(self.pending) > 65536:
            raise ValueError("Motion command too large")
        return [json.loads(line) for line in lines]


class OperatorMotionEnd(Exception):
    """Interrupt a gesture at a motor tick, then hold before the requested return."""

    def __init__(self, op: str):
        self.reason = "operator_return" if op == "return_to_start" else "operator_stop"
        super().__init__(self.reason)


def check_startup_commands(commands: MotionCommandReader) -> None:
    for command in commands.poll():
        if command.get("op") in {"stop", "return_to_start"}:
            raise OperatorMotionEnd(command["op"])
    if commands.eof:
        raise RuntimeError("API disconnected during positioning or intro")


class RealtimeIntroGripper:
    """Use audible browser speech during the gesture, with the normal stale-level hold."""

    def __init__(self, take: dict, bounds: dict, commands: MotionCommandReader):
        self.animator = SpeechGripperAnimator(take["start_pose"], bounds)
        self.commands = commands
        self.level = 0.0
        self.sent_at = 0.0

    def __call__(self, now: float, _audio_elapsed: float | None) -> float:
        for command in self.commands.poll():
            op = command.get("op")
            if op in {"stop", "return_to_start"}:
                raise OperatorMotionEnd(op)
            if op == "speech_level":
                level = float(command["level"])
                sent_at = float(command.get("sent_at", now))
                if not math.isfinite(level) or not 0 <= level <= 1 or not math.isfinite(sent_at):
                    raise ValueError("Invalid intro speech level or timestamp")
                self.level, self.sent_at = level, sent_at
            elif op == "speech_end":
                self.level = 0.0
        if self.commands.eof:
            raise RuntimeError("API disconnected during intro")
        level = self.level if 0 <= now - self.sent_at <= PLAYBACK_TIMEOUT_S else 0.0
        return self.animator.goal(now, level)["gripper"]


def hold_and_animate(controller: FluxStartController, rest: dict,
                     report: dict | None = None, report_path: Path | None = None,
                     *, start_pose: dict | None = None,
                     intro_speech: RealtimeIntroGripper | None = None,
                     commands: MotionCommandReader | None = None) -> str:
    gripper = rest["gripper"]
    animator = intro_speech.animator if intro_speech else SpeechGripperAnimator(rest, controller.bounds)
    if intro_speech:
        animator.rebase(rest, time.monotonic())
    gaze = FaceTrackingController(controller.bounds)
    head_tilt = None
    gaze_error = None
    gaze_request_id = None
    last_goal = rest.copy()
    task_active = False
    last_level_at = intro_speech.sent_at if intro_speech else 0.0
    audio_level: float | None = intro_speech.level if intro_speech else None
    last_heartbeat = time.monotonic()
    last_health = 0.0
    commands = commands or (intro_speech.commands if intro_speech else MotionCommandReader(sys.stdin.fileno()))
    while True:
        tick = time.monotonic()
        if tick - last_heartbeat > HEARTBEAT_TIMEOUT_S:
            return "browser_heartbeat_timeout"
        incoming = commands.poll()
        if commands.eof:
            return "api_disconnected"
        for command in incoming:
            op = command.get("op")
            if op == "stop":
                return "operator_stop"
            if op == "return_to_start":
                if task_active:
                    raise RuntimeError("A MolmoAct2 task is still active")
                return "operator_return"
            if op == "heartbeat":
                last_heartbeat = tick
            elif op == "speech_level":
                level = float(command["level"])
                if not math.isfinite(level) or not 0 <= level <= 1:
                    raise ValueError("Invalid speech level")
                audio_level = level
                last_level_at = float(command.get("sent_at", tick))
                if not math.isfinite(last_level_at):
                    raise ValueError("Invalid speech timestamp")
                last_heartbeat = tick
            elif op == "speech_end":
                audio_level = None
                last_heartbeat = tick
            elif op == "face_tracking":
                enabled = command.get("enabled")
                search = command.get("search", True)
                gaze_request_id = command.get("request_id")
                was_enabled = gaze.enabled
                head_tilt = None
                gaze.disable()
                gaze_error = None
                if was_enabled or (enabled is True and not task_active):
                    # A hold failure must propagate to final verified cleanup,
                    # never masquerade as a harmless rejected mode request.
                    rest = establish_measured_hold(controller)
                    last_goal = rest.copy()
                    gripper = rest["gripper"]
                    if animator is not None:
                        animator.rebase(rest, time.monotonic())
                try:
                    if type(enabled) is not bool or type(search) is not bool:
                        raise ValueError("Invalid face-tracking mode")
                    if gaze_request_id is not None and (not isinstance(gaze_request_id, str)
                                                        or len(gaze_request_id) > 128):
                        raise ValueError("Invalid face-tracking request ID")
                    if enabled and task_active:
                        raise ValueError("Face tracking is unavailable during a task")
                    if enabled:
                        gaze.enable(rest, time.monotonic(), search=search,
                                    search_direction=command.get("search_direction", "right"))
                        head_tilt = HeadTiltAnimator(rest["wrist_roll"], controller.bounds["wrist_roll"],
                                                     time.monotonic())
                except ValueError as exc:
                    gaze.disable()
                    gaze.state = "blocked"
                    gaze_error = str(exc)
                if report is not None and report_path is not None:
                    report["face_tracking"] = {**gaze.status(), "error": gaze_error,
                                               "request_id": gaze_request_id}
                    report["speech_gripper_available"] = animator is not None
                    write_report(report_path, report)
            elif op == "face_observation":
                # The API owns frame capture timestamps; browser coordinates
                # never enter this private motor-command channel.
                gaze.observe(command.get("observation"), time.monotonic())
            elif op in {"task_active", "task_inactive", "snapshot", "execute", "reset_to_start"}:
                reply_path = Path(command["reply_path"])
                try:
                    if op == "reset_to_start":
                        if task_active or start_pose is None:
                            raise RuntimeError("Reset requires a held arm and recorded start pose")
                        gaze.disable()
                        head_tilt = None
                        audio_level = None
                        last_level_at = 0.0
                        if report is not None and report_path is not None:
                            report["state"] = "resetting"
                            report["speech_gripper_available"] = False
                            write_report(report_path, report)
                        move_to_recorded_start(controller, start_pose,
                                               speed_multiplier=CONVERSATION_POSITIONING_SPEED)
                        verify_recorded_start(controller, start_pose)
                        rest = establish_measured_hold(controller)
                        last_goal = rest.copy()
                        gripper = rest["gripper"]
                        animator = SpeechGripperAnimator(rest, controller.bounds)
                        response = {"status": "reset", "measured_after": rest,
                                    "followerTorqueHolding": True, "speechGripperAvailable": True}
                        if report is not None and report_path is not None:
                            report.update(state="holding", rest_pose=rest, task_was_started=True,
                                          speech_gripper_available=True, face_tracking=gaze.status())
                            write_report(report_path, report)
                    elif op == "task_active":
                        if task_active:
                            raise RuntimeError("A MolmoAct2 task is already active")
                        gaze.disable()
                        head_tilt = None
                        gaze_error = None
                        rest = establish_measured_hold(controller)
                        last_goal = rest.copy()
                        gripper = rest["gripper"]
                        task_active = True
                        audio_level = None
                        response = {"status": "task_active", "measured_after": rest}
                        if report is not None and report_path is not None:
                            report["state"] = "task"
                            report["task_was_started"] = True
                            report["speech_gripper_available"] = False
                            report["face_tracking"] = {**gaze.status(), "error": gaze_error,
                                                       "request_id": gaze_request_id}
                            write_report(report_path, report)
                    elif op == "task_inactive":
                        if not task_active:
                            raise RuntimeError("No active MolmoAct2 task")
                        rest = establish_measured_hold(controller)
                        last_goal = rest.copy()
                        gaze.disable()
                        gripper = rest["gripper"]
                        task_active = False
                        audio_level = None
                        try:
                            animator = SpeechGripperAnimator(rest, controller.bounds)
                        except ValueError:
                            # An open or occupied gripper must not be moved by speech.
                            animator = None
                        response = {"status": "task_inactive", "measured_after": rest,
                                    "speechGripperAvailable": animator is not None}
                        if report is not None and report_path is not None:
                            report["state"] = "holding"
                            report["rest_pose"] = rest
                            report["speech_gripper_available"] = animator is not None
                            report["task_was_started"] = True
                            write_report(report_path, report)
                    elif op == "snapshot":
                        if not task_active:
                            raise RuntimeError("No active MolmoAct2 task")
                        response = snapshot(controller, "molmoact2", Path(command["observation_path"]))
                    else:
                        if not task_active:
                            raise RuntimeError("No active MolmoAct2 task")
                        actions_path = _owned_path(Path(command["actions_path"]), "ui-robot-actions-")
                        actions = json.loads(actions_path.read_text())
                        response = execute_actions(
                            controller, "molmoact2", command["observed_state"], actions,
                            epoch_path=Path(command["epoch_path"]), epoch=command["epoch"],
                            listen_for_release=False)
                    _save_reply(reply_path, response)
                except Exception as exc:
                    establish_measured_hold(controller)
                    _save_reply(reply_path, {"status": "rejected", "error": f"{type(exc).__name__}: {exc}"})
                    if op == "reset_to_start":
                        raise  # Final cleanup holds measured pose; never resume old goals.
                last_heartbeat = time.monotonic()
            else:
                raise ValueError("Unsupported conversation motion command")
        if not task_active:
            motion_now = time.monotonic()
            # A single owner composes gaze and speech. Never send the speech
            # animator's old six-joint rest pose over current gaze targets.
            goal = last_goal.copy()
            if gaze.enabled:
                measured = controller.read("Present_Position")
                goal.update(gaze.tick(motion_now, measured))
                if head_tilt is not None:
                    goal["wrist_roll"] = head_tilt.goal(
                        motion_now, measured["wrist_roll"], active=gaze.state == "tracking")
            if animator is not None:
                speech_goal = animator.goal(motion_now, audio_level
                                           if motion_now - last_level_at < PLAYBACK_TIMEOUT_S else None)
                goal["gripper"] = speech_goal["gripper"]
            if goal != last_goal:
                controller.robot.bus.sync_write("Goal_Position", goal)
                if gaze.enabled:
                    assert_goal_echo(controller, goal)
                last_goal = goal
                gripper = goal["gripper"]
        if tick - last_health >= 1:
            controller.health(expect_torque=1)
            if report is not None and report_path is not None:
                report["face_tracking"] = {**gaze.status(), "error": gaze_error,
                                           "request_id": gaze_request_id}
                write_report(report_path, report)
            last_health = tick
        time.sleep(max(0, 1 / RATE_HZ - (time.monotonic() - tick)))


def verify_recorded_start(controller: FluxStartController, start_pose: dict) -> dict:
    """Confirm the return actually settled before reporting it as complete."""
    deadline = time.monotonic() + 3.0
    while True:
        measured = controller.read("Present_Position")
        if all(abs(measured[name] - value) <= (3.0 if name == "gripper" else 2.5)
               for name, value in start_pose.items()):
            controller.health(expect_torque=1)
            return measured
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Recorded start pose not reached: target={start_pose}, measured={measured}")
        time.sleep(0.1)


def run(report_path: Path, take_path: Path, *, skip_intro: bool = False,
        realtime_intro: bool = False, intro_end_pose: bool = False) -> int:
    skip_intro = skip_intro or intro_end_pose
    report = {"state": "starting", "take": str(take_path.resolve()), "intro_skipped": skip_intro,
              "positioning_target": "intro_end" if intro_end_pose else "intro_start",
              "realtime_intro": realtime_intro,
              "started_at_unix": time.time()}
    write_report(report_path, report)
    controller = None
    try:
        controller = FluxStartController(temperature_limit_c=CONVERSATION_TEMPERATURE_LIMIT_C)
        take, samples = load_take(take_path, controller.bounds)
        # load_take validates every recorded joint target against calibration.
        target_pose = samples[-1]["target"].copy() if intro_end_pose else take["start_pose"]
        commands = MotionCommandReader(sys.stdin.fileno())
        check_interrupt = lambda: check_startup_commands(commands)
        intro_gripper = (None if skip_intro else
                         RealtimeIntroGripper(take, controller.bounds, commands)
                         if realtime_intro else prepare_intro_gripper(take, controller.bounds))
        report["state"] = "positioning"
        write_report(report_path, report)
        connect_follower(controller)
        limit_gripper_torque(controller)
        try:
            report["positioning"] = move_to_recorded_start(
                controller, target_pose, speed_multiplier=CONVERSATION_POSITIONING_SPEED,
                check_interrupt=check_interrupt)
            if not intro_end_pose:
                report["positioning_measured_start"] = verify_recorded_start(controller, target_pose)
            if not skip_intro:
                report["state"] = "intro"
                write_report(report_path, report)
                report["intro_gripper_mode"] = "realtime_audio" if realtime_intro else "audio_envelope"
                replay(controller, take, samples, report, gripper_goal=intro_gripper,
                       play_audio=not realtime_intro,
                       check_interrupt=None if realtime_intro else check_interrupt)
            # Hold either the verified pre-intro start or the end of the intro.
            rest = establish_measured_hold(controller)
            if intro_end_pose:
                report["positioning_measured_end"] = rest
            report["rest_pose"] = rest
            report["initial_hold_verified"] = True
            report["state"] = "holding"
            write_report(report_path, report)
            speech_options = {"intro_speech": intro_gripper} if realtime_intro and not skip_intro else {}
            report["stop_reason"] = hold_and_animate(controller, rest, report, report_path,
                                                    start_pose=take["start_pose"], commands=commands, **speech_options)
        except OperatorMotionEnd as end:
            report["stop_reason"] = end.reason
            report["interrupted_hold"] = establish_measured_hold(controller)
        if report["stop_reason"] == "operator_return":
            report["state"] = "returning"
            write_report(report_path, report)
            report["return_positioning"] = move_to_recorded_start(
                controller, take["start_pose"], speed_multiplier=CONVERSATION_POSITIONING_SPEED)
            report["return_measured_start"] = verify_recorded_start(controller, take["start_pose"])
            report["returned_to_start"] = True
        report["state"] = "stopped"
    except BaseException as exc:
        report["state"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if controller is not None and controller.robot.bus.is_connected:
            try:
                report["hold_position"] = establish_measured_hold(controller)
                report["follower_torque_holding"] = True
            except BaseException as exc:
                report["follower_torque_holding"] = False
                report["state"] = "failed"
                report["cleanup_error"] = f"Follower hold unverified: {exc}"
                print("Follower hold unverified; support the arm and use the power cutoff if needed.", flush=True)
            finally:
                if report.get("follower_torque_holding"):
                    try:
                        controller.robot.bus.disconnect(disable_torque=False)
                    except BaseException as exc:
                        report["state"] = "failed"
                        report["cleanup_error"] = f"Follower disconnect: {exc}"
        report["ended_at_unix"] = time.time()
        write_report(report_path, report)
    return 0 if report["state"] == "stopped" else 1


def return_only(report_path: Path, take_path: Path) -> int:
    """Complete an explicitly requested return after a previous call stopped holding."""
    report = {"state": "returning", "take": str(take_path.resolve()),
              "started_at_unix": time.time()}
    write_report(report_path, report)
    controller = None
    try:
        controller = FluxStartController(temperature_limit_c=CONVERSATION_TEMPERATURE_LIMIT_C)
        take, _ = load_take(take_path, controller.bounds)
        connect_follower(controller)
        limit_gripper_torque(controller)
        report["return_positioning"] = move_to_recorded_start(
            controller, take["start_pose"], speed_multiplier=CONVERSATION_POSITIONING_SPEED)
        report["return_measured_start"] = verify_recorded_start(controller, take["start_pose"])
        report["returned_to_start"] = True
        report["state"] = "stopped"
    except BaseException as exc:
        report["state"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if controller is not None and controller.robot.bus.is_connected:
            try:
                report["hold_position"] = establish_measured_hold(controller)
                report["follower_torque_holding"] = True
            except BaseException as exc:
                report["follower_torque_holding"] = False
                report["state"] = "failed"
                report["cleanup_error"] = f"Follower hold unverified: {exc}"
            finally:
                if report.get("follower_torque_holding"):
                    try:
                        controller.robot.bus.disconnect(disable_torque=False)
                    except BaseException as exc:
                        report["state"] = "failed"
                        report["cleanup_error"] = f"Follower disconnect: {exc}"
        report["ended_at_unix"] = time.time()
        write_report(report_path, report)
    return 0 if report["state"] == "stopped" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--take", type=Path, default=ACTIVE_TAKE)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--return-only", action="store_true")
    mode.add_argument("--skip-intro", action="store_true")
    mode.add_argument("--intro-end-pose", action="store_true",
                      help="Move directly to the final recorded intro pose without playback")
    parser.add_argument("--realtime-intro", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt("SIGTERM")))
    raise SystemExit(return_only(args.report, args.take) if args.return_only
                     else run(args.report, args.take, skip_intro=args.skip_intro,
                              realtime_intro=args.realtime_intro, intro_end_pose=args.intro_end_pose))


if __name__ == "__main__":
    main()
