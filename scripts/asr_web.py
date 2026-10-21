#!/usr/bin/env python3
"""Local SO-101 speech UI API with isolated policies and a guarded motor owner."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from asr_transcribe import MODEL_PATH, load_model, transcribe
from model_inference import (infer as run_model_inference,
                             models as available_models,
                             predict_physical_chunk)
from model_sessions import session as policy_session
from live_camera_session import camera_session
from shared_camera_stream import (PhysicalCameraLeaseBusy, camera_switch_guard,
                                  require_no_physical_client)
from face_tracking_session import FaceTrackingSession
from local_speech_worker import LocalSpeechWorker
from teleoperation_session import TeleoperationSession
import lm_studio_conversation as conversation_llm
from local_robot_conversation import LocalConversations
from project_info import get_project_info
from creator_info import get_creator_info
import realtime_voice
import realtime_web_search


ROOT = Path(__file__).resolve().parents[1]
UI_DIST = ROOT / "ui" / "dist"
POSE_CONFIG = ROOT / "config" / "flux3_start_pose.json"
FLUX_PYTHON = ROOT / "environments" / "robot" / ".venv" / "bin" / "python"
RESET_RUNNER = ROOT / "scripts" / "ui_robot_holder.py"
TORQUE_RUNNER = ROOT / "scripts" / "flux3_ui_torque.py"
TELEOP_RUNNER = ROOT / "scripts" / "leader_teleoperate.py"
LEADER_PORT = Path("/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B41533008-if00")
TTS_PYTHON = ROOT / "environments" / "tts" / ".venv" / "bin" / "python"
TTS_MODEL = ROOT / "models" / "tts" / "qwen3-tts-1.7b-customvoice"
TTS_MANIFEST = ROOT / "environments" / "tts" / "model-manifest.json"
PIPER_PYTHON = ROOT / "environments" / "piper" / ".venv" / "bin" / "python"
PIPER_MODEL = ROOT / "models" / "tts" / "piper" / "de_DE-thorsten-medium.onnx"
PIPER_KERSTIN_MODEL = ROOT / "models" / "tts" / "piper" / "de_DE-kerstin-low.onnx"
PIPER_AMY_MODEL = ROOT / "models" / "tts" / "piper" / "en_US-amy-medium.onnx"
PIPER_RYAN_MODEL = ROOT / "models" / "tts" / "piper" / "en_US-ryan-medium.onnx"
PIPER_ALAN_MODEL = ROOT / "models" / "tts" / "piper" / "en_GB-alan-medium.onnx"
PIPER_JENNY_MODEL = ROOT / "models" / "tts" / "piper" / "en_GB-jenny_dioco-medium.onnx"
PIPER_VOICE_NAMES = ("Thorsten", "Kerstin", "Amy", "Ryan", "Alan", "Jenny")
QwenSpeakerName = Literal["Ryan", "Aiden", "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ono_Anna", "Sohee"]
PiperVoiceName = Literal["Thorsten", "Kerstin", "Amy", "Ryan", "Alan", "Jenny"]
INTRO_TAKE = ROOT / "assets" / "demo" / "intro" / "active.json"
CONVERSATION_MOTION_RUNNER = ROOT / "scripts" / "conversation_motion.py"
tts_worker = LocalSpeechWorker(TTS_PYTHON, ROOT / "scripts" / "tts_worker.py", "tts")
piper_worker = LocalSpeechWorker(PIPER_PYTHON, ROOT / "scripts" / "piper_tts_worker.py", "piper")
teleoperation_session = TeleoperationSession(FLUX_PYTHON, TELEOP_RUNNER, ROOT)
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_AUDIO_SECONDS = 30
_model = None
_model_lock = threading.Lock()
_asr_loading = False
_asr_error: str | None = None
_policy_lock = threading.Lock()
_reset_guard = threading.Lock()
_reset_state = "idle"
_reset_process: subprocess.Popen | None = None
_reset_report_path: Path | None = None
_reset_fault: str | None = None
_return_running = False
_holder_command_lock = threading.Lock()
_task_guard = threading.Lock()
_active_task: dict | None = None
_last_task: dict | None = None
_torque_guard = threading.Lock()
_torque_state = "idle"
_torque_process: subprocess.Popen | None = None
_torque_report_path: Path | None = None
_torque_fault: str | None = None
_torque_verified_off = False
_conversation_motion_guard = threading.Lock()
_conversation_motion_process: subprocess.Popen | None = None
_conversation_motion_report: Path | None = None
_conversation_motion_id: str | None = None
_conversation_motion_fault: str | None = None
_conversation_motion_return_requested = False
_conversation_task_start_guard = threading.Lock()
_conversation_task_calls: dict[tuple[str, str], dict] = {}
_realtime_motion_sessions: set[str] = set()
local_conversations = LocalConversations(conversation_llm.tool_reply)
_conversation_robot_reset_session: str | None = None
_conversation_robot_reset_cancel = threading.Event()
_conversation_robot_reset_results: dict[tuple[str, str], dict] = {}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Warm ASR for both direct script and ASGI-server launches."""
    recover_torque_reset_fault()
    start_asr_warmup()
    try:
        yield
    finally:
        try:
            face_tracking_session.command("stop")
        except (RuntimeError, OSError):
            logging.getLogger(__name__).exception("Face tracking shutdown failed")


app = FastAPI(title="SO-101 local speech interface", docs_url=None, redoc_url=None,
              lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
)


class ModelRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    liveCamera: bool = False


class Insta360ViewRequest(BaseModel):
    model_config = {"extra": "forbid"}
    yaw: float = Field(ge=-180, le=180, allow_inf_nan=False, strict=True)
    pitch: float = Field(ge=-90, le=90, allow_inf_nan=False, strict=True)
    roll: float = Field(ge=-180, le=180, allow_inf_nan=False, strict=True)
    zoom: float = Field(default=1.0, ge=1, le=2, allow_inf_nan=False, strict=True)


class CameraBrightnessRequest(BaseModel):
    model_config = {"extra": "forbid"}
    value: int = Field(strict=True)


class CameraExposureRequest(BaseModel):
    model_config = {"extra": "forbid"}
    value: int = Field(strict=True)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    speaker: QwenSpeakerName = "Ryan"
    engine: Literal["qwen", "piper"] = "qwen"
    voice: PiperVoiceName = "Thorsten"
    language: Literal["German", "English"] = "German"


class PrepareConversationRequest(BaseModel):
    mode: Literal["local", "piper"] = "local"
    voice: PiperVoiceName = "Thorsten"


class RealtimeVoiceRequest(BaseModel):
    voice: Literal["marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"] = "marin"
    voiceOnly: bool = False
    language: Literal["German", "English"] = "German"


def piper_model(voice: str) -> Path:
    return {
        "Thorsten": PIPER_MODEL, "Kerstin": PIPER_KERSTIN_MODEL,
        "Amy": PIPER_AMY_MODEL, "Ryan": PIPER_RYAN_MODEL,
        "Alan": PIPER_ALAN_MODEL, "Jenny": PIPER_JENNY_MODEL,
    }[voice]


def piper_voice_ready(voice: str) -> bool:
    if voice not in PIPER_VOICE_NAMES:
        return False
    model = piper_model(voice)
    return PIPER_PYTHON.is_file() and model.is_file() and model.with_suffix(".onnx.json").is_file()


def follower_port_available() -> bool:
    """Read-only preflight for the configured Follower serial device."""
    try:
        port = json.loads(POSE_CONFIG.read_text())["port"]
        return isinstance(port, str) and Path(port).is_char_device()
    except (OSError, ValueError, KeyError, TypeError):
        return False


class ConversationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    previousResponseId: str | None = Field(default=None, pattern=r"^resp_[A-Za-z0-9_-]+$", max_length=128)


class ConversationMotionStart(BaseModel):
    model_config = {"extra": "forbid"}
    skipIntro: bool = Field(default=False, strict=True)
    realtimeIntro: bool = Field(default=False, strict=True)


class ConversationMotionLevel(BaseModel):
    sessionId: str = Field(pattern=r"^[a-f0-9]{32}$")
    level: float = Field(ge=0, le=1)


class ConversationMotionSession(BaseModel):
    sessionId: str = Field(pattern=r"^[a-f0-9]{32}$")
    returnToStart: bool = False


class FaceTrackingRequest(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["preview", "enable", "disable", "stop"]
    sessionId: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    search: bool = True
    searchDirection: Literal["left", "right"] = "right"
    mode: Literal["realtime"] = "realtime"


class ConversationRobotReset(BaseModel):
    model_config = {"extra": "forbid"}
    sessionId: str = Field(pattern=r"^[a-f0-9]{32}$")
    callId: str = Field(min_length=1, max_length=200)


class ConversationTaskRequest(BaseModel):
    sessionId: str = Field(pattern=r"^[a-f0-9]{32}$")
    instruction: str = Field(min_length=1, max_length=180)
    callId: str = Field(min_length=1, max_length=200)


class RealtimePreloadRequest(BaseModel):
    sessionId: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


def retire_failed_conversation_motion_locked(*, include_stopped: bool = False) -> None:
    """Release an exited failed process; its report remains available for diagnosis."""
    global _conversation_motion_process
    process = _conversation_motion_process
    path = _conversation_motion_report
    if process is None or process.poll() is None or path is None:
        return
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    stopped = (include_stopped and report.get("state") == "stopped"
               and report.get("follower_torque_holding") is True and not report.get("cleanup_error"))
    if (report.get("state") == "failed" or stopped) and _conversation_motion_process is process:
        _conversation_motion_process = None


def conversation_motion_status() -> dict:
    with _conversation_motion_guard:
        retire_failed_conversation_motion_locked()
        process = _conversation_motion_process
        path = _conversation_motion_report
        session_id = _conversation_motion_id
        fault = _conversation_motion_fault
    try:
        report = json.loads(path.read_text()) if path and path.is_file() else {}
    except (OSError, ValueError):
        report = {}
    if (process is None and report.get("session_closed")
            and report.get("follower_torque_holding") is True and not report.get("cleanup_error")):
        return {"state": "idle", "sessionId": session_id, "active": False,
                "occupied": False, "returnAvailable": False, "error": None,
                "followerTorqueHolding": True}
    state = report.get("state", "starting" if process and process.poll() is None else "idle")
    if process is not None and process.poll() is not None and state not in {"stopped", "failed"}:
        state = "failed"
        fault = "Bewegungscontroller endete ohne Abschlussbericht. Haltezustand prüfen."
    return {"state": state, "sessionId": session_id,
            "active": process is not None and process.poll() is None,
            "occupied": process is not None,
            "returnAvailable": (state == "stopped" and session_id is not None
                                and recoverable_conversation_report(session_id) is not None),
            "error": report.get("cleanup_error") or report.get("error") or fault,
            "followerTorqueHolding": report.get("follower_torque_holding"),
            "initialHoldVerified": report.get("initial_hold_verified", False),
            "introDuration": report.get("planned_duration_s"),
            "realtimeIntro": report.get("realtime_intro", False),
            "restPose": report.get("rest_pose"),
            "speechGripperAvailable": report.get("speech_gripper_available", True),
            "taskWasStarted": report.get("task_was_started", False),
            "returnRequested": _conversation_motion_return_requested,
            "faceTracking": report.get("face_tracking", {})}


def recoverable_conversation_report(session_id: str) -> dict | None:
    if re.fullmatch(r"[a-f0-9]{32}", session_id) is None:
        return None
    path = ROOT / "outputs" / f"conversation-motion-{session_id}.json"
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return_path = ROOT / "outputs" / f"conversation-return-{session_id}.json"
    try:
        returned = json.loads(return_path.read_text()) if return_path.is_file() else {}
    except (OSError, ValueError):
        returned = {}
    ended = report.get("ended_at_unix")
    if (report.get("session_closed") or returned.get("session_closed")
            or report.get("cleanup_error") or returned.get("cleanup_error")
            or report.get("state") != "stopped" or report.get("follower_torque_holding") is not True
            or report.get("returned_to_start") is True or returned.get("returned_to_start") is True
            or not isinstance(ended, (int, float))
            or not 0 <= time.time() - ended <= 1800):
        return None
    return report


def latest_recoverable_conversation() -> tuple[str, dict] | None:
    directory = ROOT / "outputs"
    for path in sorted(directory.glob("conversation-motion-*.json"),
                       key=lambda item: item.stat().st_mtime, reverse=True):
        session_id = path.stem.removeprefix("conversation-motion-")
        if re.fullmatch(r"[a-f0-9]{32}", session_id) is None:
            continue
        report = recoverable_conversation_report(session_id)
        # Never resurrect an older call after the latest one has ended.
        return (session_id, report) if report is not None else None
    return None


def send_conversation_motion(session_id: str, command: dict, *, mark_return: bool = False) -> None:
    global _conversation_motion_return_requested
    with _conversation_motion_guard:
        process = _conversation_motion_process
        if session_id != _conversation_motion_id or process is None or process.poll() is not None:
            raise RuntimeError("Gesprächsbewegung ist nicht aktiv.")
        encoded = (json.dumps(command, allow_nan=False) + "\n").encode()
        if len(encoded) > 4096 or os.write(process.stdin.fileno(), encoded) != len(encoded):
            raise RuntimeError("Bewegungscontroller konnte nicht erreicht werden.")
        if mark_return:
            _conversation_motion_return_requested = True


def face_tracking_task_active() -> bool:
    with _task_guard:
        return _active_task is not None or _conversation_robot_reset_session is not None


face_tracking_session = FaceTrackingSession(
    camera_session, lambda: conversation_motion_status(),
    lambda session_id, command: send_conversation_motion(session_id, command),
    face_tracking_task_active,
)


@app.get("/api/conversation/face-tracking/status")
async def conversation_face_tracking_status() -> dict:
    return await run_in_threadpool(face_tracking_session.status)


@app.post("/api/conversation/face-tracking")
async def conversation_face_tracking(request: FaceTrackingRequest, browser: Request) -> dict:
    if browser.headers.get("x-so101-conversation") != "operator-face-tracking":
        raise HTTPException(status_code=403, detail="Face-Tracking erfordert eine ausdrückliche Auswahl.")
    def apply():
        # Serializes enable with the beginning of a manipulation request.
        with _conversation_task_start_guard:
            if (request.action == "enable" and request.sessionId not in _realtime_motion_sessions
                    and not local_conversations.has_motion(request.sessionId)):
                raise RuntimeError("Face-Tracking erfordert eine aktive Realtime- oder Piper-Gesprächssitzung.")
            return face_tracking_session.command(request.action, request.sessionId, request.search,
                                                 request.searchDirection, require_owner=True)
    try:
        return await run_in_threadpool(apply)
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def stop_conversation_motion(session_id: str, return_to_start: bool = False) -> dict:
    global _conversation_motion_process, _conversation_motion_report, _conversation_motion_id
    global _conversation_motion_return_requested
    local_conversations.close_motion(session_id)
    if _conversation_robot_reset_session == session_id:
        _conversation_robot_reset_cancel.set()
    with _task_guard:
        if (_active_task is not None and _active_task.get("conversationSessionId") == session_id):
            raise RuntimeError("Zuerst MolmoAct2 stoppen und den Follower-Halt abwarten.")
    face_tracking_session.disable("Gespräch wird beendet.")
    _realtime_motion_sessions.discard(session_id)
    with _conversation_motion_guard:
        process = _conversation_motion_process
        path = _conversation_motion_report
        if session_id != _conversation_motion_id or path is None:
            raise RuntimeError("Diese Gesprächssitzung ist nicht aktiv.")
        state = None
        if process is not None and process.poll() is None:
            try:
                state = json.loads(path.read_text()).get("state") if path and path.is_file() else None
            except (OSError, ValueError):
                state = None
            if state == "holding" and not _conversation_motion_return_requested:
                try:
                    command = b'{"op":"return_to_start"}\n' if return_to_start else b'{"op":"stop"}\n'
                    if os.write(process.stdin.fileno(), command) != len(command):
                        raise RuntimeError("Bewegungscontroller konnte den Stop-Befehl nicht empfangen.")
                except (OSError, RuntimeError):
                    process.terminate()
            else:
                # During positioning or intro replay, SIGTERM interrupts the
                # timestamped motion. Its finally block verifies torque-on hold.
                process.terminate()
    try:
        if process is not None:
            process.wait(timeout=90 if return_to_start and state == "holding" else 12)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Rückfahrt oder Halt antwortet nicht; Haltezustand prüfen.") from exc
    try:
        report = json.loads(path.read_text()) if path else {}
    except (OSError, ValueError):
        report = {}
    if report.get("follower_torque_holding") is not True or report.get("cleanup_error"):
        # The exited process no longer owns the serial port. Retain its report
        # for diagnosis while allowing a new controller to perform fresh motor
        # checks before the next conversation moves the arm.
        with _conversation_motion_guard:
            if _conversation_motion_process is process:
                _conversation_motion_process = None
        raise RuntimeError(report.get("cleanup_error") or report.get("error") or
                           "Follower-Halt konnte nicht bestätigt werden.")
    interrupted = report.get("error") == "KeyboardInterrupt: SIGTERM"
    if return_to_start and report.get("returned_to_start") is not True and not interrupted:
        raise RuntimeError(report.get("cleanup_error") or report.get("error") or
                           "Rückfahrt zur Anfangspose konnte nicht bestätigt werden.")
    with _conversation_motion_guard:
        if (_conversation_motion_id == session_id and _conversation_motion_report == path
                and (_conversation_motion_process is process or _conversation_motion_process is None)):
            # Keep the diagnostic error on disk, but acknowledge this ended call.
            report["session_closed"] = True
            temporary = path.with_suffix(".closed.tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False) + "\n")
            temporary.replace(path)
            _conversation_motion_process = None
            # Retain identity/report so repeated stop requests are idempotent.
            _conversation_motion_return_requested = False
    return {"status": "stopped", "followerTorqueHolding": True,
            "returnedToStart": report.get("returned_to_start") is True}


def launch_conversation_motion_locked(session_id: str, *, skip_intro: bool = False,
                                      realtime_intro: bool = False,
                                      intro_end_pose: bool = False) -> subprocess.Popen:
    """Shared startup, called with the policy and conversation-motion locks held."""
    global _conversation_motion_process, _conversation_motion_report, _conversation_motion_id
    global _conversation_motion_return_requested
    report = ROOT / "outputs" / f"conversation-motion-{session_id}.json"
    # A restarted process must never inherit its predecessor's 'holding' report.
    previous_report = report.read_text() if report.exists() else None
    if previous_report is not None:
        archive = report.with_name(f"{report.stem}-previous-{uuid.uuid4().hex}.json")
        report.replace(archive)
    report.write_text(json.dumps({"state": "starting", "intro_skipped": skip_intro or intro_end_pose,
                                 "positioning_target": "intro_end" if intro_end_pose else "intro_start",
                                 "realtime_intro": realtime_intro}))
    try:
        with report.with_suffix(".log").open("a") as log:
            process = subprocess.Popen(
                [str(FLUX_PYTHON), str(CONVERSATION_MOTION_RUNNER),
                 "--take", str(INTRO_TAKE), "--report", str(report)]
                + (["--intro-end-pose"] if intro_end_pose else ["--skip-intro"] if skip_intro else [])
                + (["--realtime-intro"] if realtime_intro else []),
                cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
            )
    except OSError:
        # Retain the verified old hold if the replacement cannot be launched.
        if previous_report is not None:
            report.write_text(previous_report)
        raise
    _conversation_motion_process = process
    _conversation_motion_report = report
    _conversation_motion_id = session_id
    _conversation_motion_return_requested = False
    return process


def restart_conversation_motion(session_id: str) -> dict:
    """Replace only the motor process, preserving the logical voice session."""
    with _conversation_motion_guard:
        old = _conversation_motion_process
        path = _conversation_motion_report
        if (session_id != _conversation_motion_id or old is None or old.poll() is not None
                or _conversation_motion_return_requested or _conversation_robot_reset_cancel.is_set()):
            raise RuntimeError("Gespräch wurde beendet; Controller-Neustart abgebrochen.")
        # Normal stop verifies the measured hold and disconnects with torque on.
        try:
            command = b'{"op":"stop"}\n'
            if os.write(old.stdin.fileno(), command) != len(command):
                raise OSError("Stop-Befehl unvollständig")
        except OSError:
            old.terminate()
    try:
        old.wait(timeout=12)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Alter Controller läuft noch; kein neuer Controller gestartet. Haltezustand prüfen.") from exc
    try:
        report = json.loads(path.read_text()) if path else {}
    except (OSError, ValueError):
        report = {}
    if report.get("follower_torque_holding") is not True or report.get("cleanup_error"):
        raise RuntimeError(report.get("cleanup_error") or "Follower-Halt beim Controller-Wechsel nicht bestätigt.")
    with _conversation_motion_guard:
        if (session_id != _conversation_motion_id or _conversation_motion_process is not old
                or _conversation_motion_return_requested or _conversation_robot_reset_cancel.is_set()):
            raise RuntimeError("Gespräch wurde beendet; Controller-Neustart abgebrochen.")
        process = launch_conversation_motion_locked(session_id, intro_end_pose=True)
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        if _conversation_robot_reset_cancel.is_set():
            motion = conversation_motion_status()
            if motion["sessionId"] == session_id and motion["active"]:
                stop_conversation_motion(session_id)
            raise RuntimeError("Controller-Neustart durch Gesprächsende abgebrochen.")
        motion = conversation_motion_status()
        if motion["sessionId"] != session_id or not motion["active"]:
            raise RuntimeError(motion.get("error") or "Neuer Controller endete vor der Startbestätigung. Haltezustand prüfen.")
        if motion["state"] == "holding" and motion.get("initialHoldVerified") is True:
            return {"status": "reset", "followerTorqueHolding": True,
                    "speechGripperAvailable": motion["speechGripperAvailable"],
                    "measured_after": motion["restPose"], "controllerRestarted": True,
                    "previousControllerPid": old.pid, "controllerPid": process.pid}
        time.sleep(.05)
    # A failed startup must not leave a positioning controller running silently.
    stop_conversation_motion(session_id)
    raise RuntimeError("Neuer Controller nicht rechtzeitig bereit; Follower hält die gemessene Position.")


@app.post("/api/conversation/motion/start")
async def conversation_motion_start(request: Request, options: ConversationMotionStart | None = None) -> dict:
    global _conversation_motion_process, _conversation_motion_report, _conversation_motion_id
    global _conversation_motion_return_requested
    if request.headers.get("x-so101-conversation") != "operator-call":
        raise HTTPException(status_code=403, detail="Gesprächsbewegung erfordert einen ausdrücklichen Anruf.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft noch.")
    try:
        if teleoperation_session.status()["occupied"]:
            raise HTTPException(status_code=409, detail="Teleoperation belegt den Follower.")
        if reset_state()[0] != "idle" or torque_state()[0] != "idle":
            raise HTTPException(status_code=409, detail="Follower ist bereits durch die UI belegt.")
        with _conversation_motion_guard:
            retire_failed_conversation_motion_locked(include_stopped=True)
            if _conversation_motion_process is not None and _conversation_motion_process.poll() is None:
                raise HTTPException(status_code=409, detail="Eine Gesprächsbewegung läuft bereits.")
            if not follower_port_available():
                return {"status": "voice-only", "sessionId": None}
            if not INTRO_TAKE.is_file() or not CONVERSATION_MOTION_RUNNER.is_file() or not FLUX_PYTHON.is_file():
                raise HTTPException(status_code=503, detail="Intro-Aufnahme oder Bewegungscontroller fehlt.")
            if _conversation_motion_fault:
                raise HTTPException(status_code=409, detail=_conversation_motion_fault)
            if _conversation_motion_process is not None:
                raise HTTPException(status_code=409, detail="Eine Gesprächsbewegung läuft bereits.")
            session_id = uuid.uuid4().hex
            launch_conversation_motion_locked(session_id, skip_intro=bool(options and options.skipIntro),
                                              realtime_intro=bool(options and options.realtimeIntro))
        return {"status": "starting", "sessionId": session_id}
    finally:
        _policy_lock.release()


@app.get("/api/conversation/motion/status")
def conversation_motion_get_status(sessionId: str | None = None) -> dict:
    current = conversation_motion_status()
    if current["occupied"] or current["state"] == "failed" or current.get("sessionId"):
        return current
    fallback = ((sessionId, recoverable_conversation_report(sessionId)) if sessionId
                else latest_recoverable_conversation())
    if fallback is None or fallback[1] is None:
        return current
    sessionId, report = fallback
    return {"state": "stopped", "sessionId": sessionId, "active": False,
            "occupied": True, "error": None, "followerTorqueHolding": True,
            "initialHoldVerified": report.get("initial_hold_verified", False),
            "introDuration": report.get("planned_duration_s"),
            "restPose": report.get("rest_pose"), "returnAvailable": True}


@app.post("/api/conversation/motion/return-stopped")
async def conversation_motion_return_stopped(request: ConversationMotionSession,
                                             browser: Request) -> dict:
    """Restart only the verified return leg after a lost browser heartbeat."""
    global _conversation_motion_process, _conversation_motion_report, _conversation_motion_id
    global _conversation_motion_return_requested, _conversation_motion_fault
    if browser.headers.get("x-so101-conversation") != "operator-end":
        raise HTTPException(status_code=403, detail="Rückfahrt erfordert Gespräch beenden.")
    if not INTRO_TAKE.is_file() or not CONVERSATION_MOTION_RUNNER.is_file() or not FLUX_PYTHON.is_file():
        raise HTTPException(status_code=503, detail="Intro-Aufnahme oder Bewegungscontroller fehlt.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft noch.")
    try:
        if teleoperation_session.status()["occupied"]:
            raise HTTPException(status_code=409, detail="Teleoperation belegt den Follower.")
        if reset_state()[0] != "idle" or torque_state()[0] != "idle":
            raise HTTPException(status_code=409, detail="Follower ist bereits durch die UI belegt.")
        with _conversation_motion_guard:
            process = _conversation_motion_process
            if process is not None and process.poll() is None:
                raise HTTPException(status_code=409, detail="Eine Gesprächsbewegung läuft bereits.")
            if process is not None and _conversation_motion_id != request.sessionId:
                raise HTTPException(status_code=409, detail="Eine andere Gesprächssitzung ist noch belegt.")
            if recoverable_conversation_report(request.sessionId) is None:
                raise HTTPException(status_code=409, detail="Rückfahrt ist für diese Sitzung nicht mehr verfügbar.")
            report_path = ROOT / "outputs" / f"conversation-return-{request.sessionId}.json"
            previous_report = report_path.read_text() if report_path.exists() else None
            if previous_report is not None:
                archive = report_path.with_name(f"{report_path.stem}-previous-{uuid.uuid4().hex}.json")
                archive.write_text(previous_report)
            # Publish the new attempt before exposing its process to status polling.
            # Otherwise a previous failed/stopped report cancels the new return.
            report_path.write_text(json.dumps({"state": "starting"}))
            try:
                with report_path.with_suffix(".log").open("a") as log:
                    process = subprocess.Popen(
                        [str(FLUX_PYTHON), str(CONVERSATION_MOTION_RUNNER),
                         "--take", str(INTRO_TAKE), "--report", str(report_path), "--return-only"],
                        cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                    )
            except OSError:
                if previous_report is not None:
                    report_path.write_text(previous_report)
                else:
                    report_path.unlink(missing_ok=True)
                raise
            _conversation_motion_process = process
            _conversation_motion_report = report_path
            _conversation_motion_id = request.sessionId
            _conversation_motion_return_requested = True
            _conversation_motion_fault = None
        return {"status": "returning", "sessionId": request.sessionId}
    finally:
        _policy_lock.release()


@app.post("/api/conversation/motion/level")
def conversation_motion_level(request: ConversationMotionLevel) -> dict:
    motion = conversation_motion_status()
    if motion["state"] in {"starting", "positioning"}:
        return {"status": "ignored"}
    if motion["state"] in {"task", "resetting"} or _conversation_robot_reset_session is not None or not motion.get("speechGripperAvailable", True):
        return {"status": "ignored"}
    if motion["state"] != "holding" and not (motion["state"] == "intro" and motion.get("realtimeIntro")):
        raise HTTPException(status_code=409, detail="Intro ist noch nicht abgeschlossen.")
    try:
        send_conversation_motion(request.sessionId, {"op": "speech_level", "level": request.level,
                                                     "sent_at": time.monotonic()})
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/api/conversation/motion/heartbeat")
def conversation_motion_heartbeat(request: ConversationMotionSession) -> dict:
    if _conversation_robot_reset_session == request.sessionId:
        return {"status": "resetting"}
    try:
        send_conversation_motion(request.sessionId, {"op": "heartbeat"})
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/api/conversation/motion/speech-end")
def conversation_motion_speech_end(request: ConversationMotionSession) -> dict:
    if _conversation_robot_reset_session == request.sessionId:
        return {"status": "resetting"}
    try:
        send_conversation_motion(request.sessionId, {"op": "speech_end"})
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/api/conversation/motion/return")
def conversation_motion_return(request: ConversationMotionSession) -> dict:
    local_conversations.close_motion(request.sessionId)
    if _conversation_robot_reset_session == request.sessionId:
        _conversation_robot_reset_cancel.set()
    face_tracking_session.disable("Rückfahrt zur Startposition.")
    with _task_guard:
        if (_active_task is not None and _active_task.get("conversationSessionId") == request.sessionId):
            raise HTTPException(status_code=409, detail="Zuerst MolmoAct2 stoppen und den Follower-Halt abwarten.")
        motion = conversation_motion_status()
        if motion["state"] not in {"starting", "positioning", "intro", "holding"}:
            raise HTTPException(status_code=409, detail="Rückfahrt ist im aktuellen Bewegungszustand nicht verfügbar.")
        try:
            send_conversation_motion(request.sessionId, {"op": "return_to_start"}, mark_return=True)
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "returning"}


@app.post("/api/conversation/motion/stop")
async def conversation_motion_stop(request: ConversationMotionSession) -> dict:
    try:
        return await run_in_threadpool(stop_conversation_motion, request.sessionId,
                                       request.returnToStart)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/conversation/robot/reset")
def conversation_robot_reset(request: ConversationRobotReset, browser: Request) -> dict:
    """Restart the motor controller without closing voice or unloading weights."""
    origin = browser.headers.get("x-so101-conversation")
    if origin not in {"operator-reset", "realtime-tool"}:
        raise HTTPException(status_code=403, detail="Reset erfordert einen Bedien- oder Sprachauftrag.")
    return reset_conversation_robot(request, origin=origin)


def reset_conversation_robot(request: ConversationRobotReset, *, origin: str, authorize=None) -> dict:
    """Shared controller operation; local tools reach it only via stored calls."""
    global _conversation_robot_reset_session
    key = (request.sessionId, request.callId)
    with _conversation_task_start_guard:
        if authorize:
            authorize()
        if key in _conversation_robot_reset_results:
            return _conversation_robot_reset_results[key]
        if _conversation_robot_reset_session is not None:
            raise HTTPException(status_code=409, detail="Roboter wird bereits zurückgesetzt.")
        motion = conversation_motion_status()
        if (motion.get("sessionId") != request.sessionId or not motion.get("active")
                or motion["state"] not in {"holding", "task"} or motion.get("returnRequested")):
            raise HTTPException(status_code=409, detail="Reset erfordert einen aktiven Gesprächsarm.")
        if origin == "realtime-tool" and request.sessionId not in _realtime_motion_sessions:
            raise HTTPException(status_code=409, detail="Realtime-Sitzung ist nicht aktiv.")
        with _task_guard:
            if _active_task and _active_task.get("conversationSessionId") != request.sessionId:
                raise HTTPException(status_code=409, detail="Ein anderer Auftrag belegt den Arm.")
        _conversation_robot_reset_cancel.clear()
        _conversation_robot_reset_session = request.sessionId
    policy_locked = False
    try:
        face_tracking_session.disable("Roboter wird zurückgesetzt.")
        request_physical_task_stop()
        # Wait for the in-flight prediction and verified task hold. Do not use
        # wait_for_stopped_task: its timeout fallback unloads the model worker.
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            motion = conversation_motion_status()
            if (motion.get("sessionId") != request.sessionId or not motion.get("active")
                    or motion.get("returnRequested")):
                raise RuntimeError("Gespräch wurde beendet; Reset abgebrochen.")
            if _policy_lock.acquire(timeout=.1):
                policy_locked = True
                break
        if not policy_locked:
            raise RuntimeError("Auftrag noch nicht angehalten; Reset nicht gestartet. Modell bleibt geladen.")
        motion = conversation_motion_status()
        if (motion.get("sessionId") != request.sessionId or motion["state"] != "holding"
                or motion.get("returnRequested") or not motion.get("active")):
            raise RuntimeError("Follower-Halt vor Reset nicht bestätigt.")
        if authorize:
            authorize()
        result = restart_conversation_motion(request.sessionId)
        if (result.get("status") != "reset" or result.get("followerTorqueHolding") is not True
                or result.get("controllerRestarted") is not True):
            raise RuntimeError("Controller-Neustart und Follower-Halt wurden nicht bestätigt.")
        result = {**result, "sessionId": request.sessionId, "modelReloaded": False}
        _conversation_robot_reset_results[key] = result
        if len(_conversation_robot_reset_results) > 256:
            del _conversation_robot_reset_results[next(iter(_conversation_robot_reset_results))]
        return result
    except (RuntimeError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        if policy_locked:
            _policy_lock.release()
        _conversation_robot_reset_session = None


@app.post("/api/conversation/task/start")
def conversation_task_start(request: ConversationTaskRequest, browser: Request) -> dict:
    """Start/update the announced Realtime instruction, with one motor owner."""
    if browser.headers.get("x-so101-conversation") != "realtime-tool":
        raise HTTPException(status_code=403, detail="Auftrag erfordert ChatGPT Realtime.")
    return start_conversation_task(request)


def start_conversation_task(request: ConversationTaskRequest, *, authorize=None,
                            timeout_s: float = 425) -> dict:
    """One shared MolmoAct2 handoff for both conversation providers."""
    if _conversation_robot_reset_session is not None:
        raise HTTPException(status_code=409, detail="Roboter wird zurückgesetzt; danach neuen Auftrag geben.")
    instruction = request.instruction.strip().rstrip(".!? ")
    if not instruction or "\n" in instruction or re.search(r"[.!?](?=\s+\S)", instruction):
        raise HTTPException(status_code=422, detail="Bitte genau einen kurzen Befehl formulieren.")
    # Warmup owns the same policy lock as inference, without an active task.
    # Retry the handoff after it finishes; never hold the start guard while
    # waiting, so reset/end can revoke the session and local tool permission.
    deadline = time.monotonic() + timeout_s
    while True:
        result = try_start_conversation_task(request, instruction, authorize=authorize)
        if result is not None:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HTTPException(status_code=504, detail="MolmoAct2-Vorbereitung hat das Zeitlimit überschritten; Auftrag nicht gestartet.")
        time.sleep(min(.1, remaining))


def try_start_conversation_task(request: ConversationTaskRequest, instruction: str,
                                *, authorize=None) -> dict | None:
    """Return None while a model operation is busy; revalidate on every retry."""
    global _active_task
    with _conversation_task_start_guard:
        if authorize:
            authorize()
        if _conversation_robot_reset_session is not None:
            raise HTTPException(status_code=409, detail="Roboter wird gerade zurückgesetzt.")
        motion = conversation_motion_status()
        if (motion["sessionId"] != request.sessionId or motion["state"] not in {"holding", "task"}
                or motion.get("active") is False or motion.get("returnRequested")):
            raise HTTPException(status_code=409, detail="Gesprächsarm ist nicht bereit.")
        call_key = (request.sessionId, request.callId)
        if call_key in _conversation_task_calls:
            return _conversation_task_calls[call_key]
        try:
            face_tracking_session.disable("MolmoAct2 übernimmt den Arm.")
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if authorize:
            authorize()
        with _task_guard:
            run = _active_task
            if run is not None:
                if (run.get("conversationSessionId") != request.sessionId
                        or run["model"] != "molmoact2" or run["stop"].is_set()):
                    raise HTTPException(status_code=409, detail="Zuerst laufende Aufgabe stoppen.")
                # Invalidate old predictions and queued frames before the new instruction.
                run["generation"] += 1
                run["prompt"] = instruction
                _write_task_epoch(run)
                run["message"] = "Neue Anweisung übernommen; alter Aktionsblock wird verworfen."
                result = {"status": "updated", "taskRun": task_status_unlocked(run)}
            else:
                result = None
        if result is None:
            if motion["state"] != "holding":
                raise HTTPException(status_code=409, detail="Ein Modelllauf wird noch beendet. Bitte kurz warten.")
            if not _policy_lock.acquire(blocking=False):
                return None
            run_id = uuid.uuid4().hex
            run = {"id": run_id, "model": "molmoact2", "prompt": instruction,
                   "state": "loading", "chunks": 0, "actions": 0, "startedAt": time.time(),
                   "endedAt": None, "message": "MolmoAct2 wird vorbereitet.",
                   "generation": 0, "inferenceGeneration": -1, "executedGeneration": -1,
                   "stop": threading.Event(), "conversationSessionId": request.sessionId,
                   "epochPath": ROOT / "outputs" / f"ui-robot-epoch-{run_id}.txt"}
            try:
                # Loading may have finished just as the operator ended the call.
                motion = conversation_motion_status()
                if (motion["sessionId"] != request.sessionId or motion["state"] != "holding"
                        or motion.get("active") is False or motion.get("returnRequested")):
                    raise RuntimeError("Gesprächsarm ist nicht mehr bereit; Auftrag nicht gestartet.")
                if authorize:
                    authorize()
                with _task_guard:
                    if _active_task is not None:
                        raise RuntimeError("Ein Modelllauf läuft bereits.")
                    _write_task_epoch(run)
                    _active_task = run
                threading.Thread(target=physical_task_loop, args=(run,),
                                 name=f"conversation-molmo-{run_id[:8]}", daemon=True).start()
                result = {"status": "loading", "taskRun": task_status_unlocked(run)}
            except BaseException as exc:
                with _task_guard:
                    if _active_task is run:
                        _active_task = None
                run["epochPath"].unlink(missing_ok=True)
                _policy_lock.release()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        _conversation_task_calls[call_key] = result
        if len(_conversation_task_calls) > 256:
            del _conversation_task_calls[next(iter(_conversation_task_calls))]
        return result


@app.get("/api/conversation/status")
def conversation_status(mode: str = "local", voice: str = "Thorsten") -> dict:
    dialogue = (conversation_llm.model_status() if mode in {"local", "piper"}
                else {"ready": False, "model": conversation_llm.MODEL})
    return {"ttsReady": TTS_PYTHON.is_file() and TTS_MANIFEST.is_file(),
            "piperReady": piper_voice_ready(voice),
            "ttsSpeaker": "Ryan", "dialogueReady": dialogue["ready"],
            "dialogueModel": dialogue["model"],
            "dialogueQuantization": dialogue.get("quantization"),
            "dialogueReason": dialogue.get("reason", ""),
            "followerPortAvailable": follower_port_available(),
            "introReady": INTRO_TAKE.is_file() and CONVERSATION_MOTION_RUNNER.is_file()
                          and FLUX_PYTHON.is_file(),
            "realtimeReady": realtime_voice.configured(),
            "realtimeTaskProtocol": 4,
            "localTaskProtocol": 1,
            "localTtsEngines": ["piper", "qwen"],
            "conversationLanguages": ["German", "English"],
            "startWithoutIntroAvailable": True,
            "robotResetAvailable": True,
            "robotResetRestartsController": True,
            "realtimeModel": realtime_voice.REALTIME_MODEL}


@app.post("/api/conversation/realtime/token")
async def conversation_realtime_token(request: Request, selection: RealtimeVoiceRequest | None = None) -> JSONResponse:
    if request.headers.get("x-so101-conversation") != "operator-call":
        raise HTTPException(status_code=403, detail="Realtime erfordert einen ausdrücklichen Anruf.")
    if not realtime_voice.configured():
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY ist auf dem UI-Server nicht gesetzt.")
    motion = conversation_motion_status()
    if selection and selection.voiceOnly:
        if motion["active"]:
            raise HTTPException(status_code=409, detail="Eine Gesprächsbewegung ist noch aktiv.")
    elif motion["state"] != "holding" and not (
            motion.get("realtimeIntro") and motion.get("active")
            and motion["state"] in {"starting", "positioning", "intro"}):
        raise HTTPException(status_code=409, detail="Gesprächsbewegung hält noch nicht.")
    try:
        secret = await run_in_threadpool(realtime_voice.create_client_secret,
                                         selection.voice if selection else "marin",
                                         selection.voiceOnly if selection else False,
                                         selection.language if selection else "German")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not (selection and selection.voiceOnly) and motion.get("sessionId"):
        _realtime_motion_sessions.add(motion["sessionId"])
    return JSONResponse(
        {"value": secret, "model": realtime_voice.REALTIME_MODEL},
        headers={"Cache-Control": "no-store"},
    )


class RealtimeWebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


@app.post("/api/conversation/realtime/search")
async def conversation_realtime_search(request: Request, search: RealtimeWebSearchRequest) -> JSONResponse:
    if request.headers.get("x-so101-conversation") != "realtime-tool":
        raise HTTPException(status_code=403, detail="Internetsuche erfordert einen Realtime-Werkzeugaufruf.")
    try:
        result = await realtime_web_search.search(search.query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/api/conversation/realtime/project-info")
def conversation_realtime_project_info(request: Request) -> JSONResponse:
    """Curated context only: independent of camera, model and motor ownership."""
    if request.headers.get("x-so101-conversation") != "realtime-tool":
        raise HTTPException(status_code=403, detail="Setup-Informationen erfordern einen Realtime-Werkzeugaufruf.")
    try:
        result = get_project_info("realtime", realtime_model=realtime_voice.REALTIME_MODEL)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Technische Hintergrundinformationen sind nicht verfügbar.") from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/api/conversation/realtime/creator-info")
def conversation_realtime_creator_info(request: Request) -> JSONResponse:
    """Small attribution lookup, without fetching a profile or acquiring devices."""
    if request.headers.get("x-so101-conversation") != "realtime-tool":
        raise HTTPException(status_code=403, detail="Projektinformationen erfordern einen Realtime-Werkzeugaufruf.")
    try:
        result = get_creator_info()
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Informationen zur Projektperson sind nicht verfügbar.") from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/api/conversation/realtime/scene")
async def conversation_realtime_scene(request: Request) -> JSONResponse:
    """Read shared camera streams; never acquire a robot or switch camera profiles."""
    if request.headers.get("x-so101-conversation") != "realtime-tool":
        raise HTTPException(status_code=403, detail="Kamerabilder erfordern einen Realtime-Werkzeugaufruf.")
    try:
        result = await run_in_threadpool(camera_session.scene_snapshot)
    except (RuntimeError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/api/conversation/realtime/molmo/preload")
async def conversation_realtime_molmo_preload(request: Request, selection: RealtimePreloadRequest) -> dict:
    """Warm policy weights before the intro, without opening cameras or motors."""
    if request.headers.get("x-so101-conversation") != "operator-call":
        raise HTTPException(status_code=403, detail="MolmoAct2-Vorladen erfordert einen ausdrücklichen Anruf.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft bereits.")
    try:
        motion = conversation_motion_status()
        if selection.sessionId:
            # Compatibility with an already open client using post-intro warmup.
            if motion["sessionId"] != selection.sessionId or motion["state"] != "holding":
                raise HTTPException(status_code=409, detail="Gesprächsarm hält noch nicht.")
        elif motion["occupied"] or reset_state()[0] != "idle" or torque_state()[0] != "idle":
            raise HTTPException(status_code=409, detail="Vorbereitung erfordert eine freie Gesprächssitzung.")
        selected = next(model for model in available_models(
            cuda_available=torch.cuda.is_available()) if model["id"] == "molmoact2")
        if not selected["available"]:
            raise HTTPException(status_code=503, detail=selected["message"])
        if policy_session.model_id not in (None, "molmoact2"):
            raise HTTPException(status_code=409, detail="Steuerungsmodell zuerst freigeben.")
        loaded = await run_in_threadpool(policy_session.preload, "molmoact2")
        if loaded.get("ready") is not True or loaded.get("hardwareCommands") is not False:
            raise RuntimeError("MolmoAct2 wurde nicht ohne Hardwarebefehle geladen.")
        return {"model": "molmoact2", "ready": True, "hardwareCommands": False}
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="MolmoAct2-Laden hat das Zeitlimit überschritten.") from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _policy_lock.release()


@app.post("/api/conversation/prepare")
async def conversation_prepare(request: PrepareConversationRequest | None = None) -> dict:
    """Warm speech models after the Steuerung policy and cameras are released."""
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Steuerungsmodell wird noch geladen oder verwendet.")
    try:
        mode = request.mode if request else "local"
        if (policy_session.model_id not in (None, "molmoact2") or
                camera_session.model_id not in (None, "conversation", "molmoact2") or
                conversation_motion_status()["active"] or
                (task_status() or {}).get("state") in {"loading", "running", "stopping"}):
            raise HTTPException(status_code=409, detail="Lokale Vorbereitung erfordert eine freie Gesprächssitzung.")
        if mode == "piper":
            voice = request.voice if request else "Thorsten"
            if not piper_voice_ready(voice):
                raise HTTPException(status_code=503, detail="Piper oder die gewählte Stimme ist nicht installiert.")
            worker = piper_worker
        else:
            if not TTS_PYTHON.is_file() or not TTS_MANIFEST.is_file():
                raise HTTPException(status_code=503, detail="Qwen3-TTS CustomVoice ist nicht installiert.")
            worker = tts_worker
        if follower_port_available() and (not INTRO_TAKE.is_file() or not CONVERSATION_MOTION_RUNNER.is_file() or not FLUX_PYTHON.is_file()):
            raise HTTPException(status_code=503, detail="Intro-Aufnahme oder Bewegungscontroller fehlt.")
        try:
            dialogue = await run_in_threadpool(conversation_llm.ensure_model_loaded)
            await run_in_threadpool(worker.ensure_ready)
            if mode == "piper":
                await run_in_threadpool(worker.request, {"op": "prepare", "voice": voice})
        except (RuntimeError, TimeoutError, OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"dialogueReady": dialogue["ready"], "ttsReady": True, "introReady": True}
    finally:
        _policy_lock.release()


class LocalConversationVoice(BaseModel):
    model_config = {"extra": "forbid"}
    voice: PiperVoiceName | QwenSpeakerName | None = None


class LocalConversationStart(LocalConversationVoice):
    engine: Literal["piper", "qwen"] = "piper"
    language: Literal["German", "English"] | None = None
    motionSessionId: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class LocalConversationTurn(LocalConversationVoice):
    text: str = Field(min_length=1, max_length=500)


class LocalConversationTool(BaseModel):
    model_config = {"extra": "forbid"}
    callId: str = Field(pattern=r"^[a-f0-9]{32}$")
    announced: bool = Field(default=False, strict=True)


def require_local_conversation_browser(browser: Request):
    if browser.headers.get("x-so101-conversation") != "local-conversation":
        raise HTTPException(status_code=403, detail="Lokales Gespräch muss ausdrücklich gestartet werden.")


def require_local_motion(session):
    local_conversations.check(session)
    motion = conversation_motion_status()
    if (not session.motion_id or motion.get("sessionId") != session.motion_id or
            not motion.get("active") or motion.get("state") not in {"holding", "task"} or
            motion.get("returnRequested")):
        raise RuntimeError("Der lokale Gesprächsarm ist nicht mehr bereit.")


@app.post("/api/conversation/local/start")
def local_conversation_start(options: LocalConversationStart, browser: Request) -> dict:
    require_local_conversation_browser(browser)
    with _conversation_task_start_guard:
        motion = conversation_motion_status()
        if options.motionSessionId:
            if (motion.get("sessionId") != options.motionSessionId or not motion.get("active") or
                    motion.get("state") != "holding" or motion.get("returnRequested") or
                    options.motionSessionId in _realtime_motion_sessions):
                raise HTTPException(status_code=409, detail="Lokales Gespräch erfordert einen bereiten Gesprächsarm.")
        elif motion.get("active"):
            raise HTTPException(status_code=409, detail="Ein anderes Gespräch belegt den Arm.")
        try:
            session_id = local_conversations.start(options.motionSessionId, options.voice, options.engine, options.language)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"sessionId": session_id, "ready": True}


@app.delete("/api/conversation/local/{session_id}")
def local_conversation_close(session_id: str, browser: Request) -> dict:
    require_local_conversation_browser(browser)
    # Revocation never waits for slow LLM inference or a completed physical task.
    local_conversations.close(session_id)
    return {"status": "closed"}


@app.post("/api/conversation/local/{session_id}/cancel")
def local_conversation_cancel(session_id: str, browser: Request) -> dict:
    require_local_conversation_browser(browser)
    try:
        local_conversations.cancel(session_id)
        return {"status": "cancelled"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/conversation/local/{session_id}/turn")
def local_conversation_turn(session_id: str, turn: LocalConversationTurn, browser: Request) -> dict:
    require_local_conversation_browser(browser)
    try:
        session = local_conversations.get(session_id)
        if session.motion_id:
            require_local_motion(session)
        return local_conversations.turn(session_id, turn.text, {
            "motion": conversation_motion_status(), "task": task_status(),
            "note": "Task status does not verify task success. No automatic restart."}, voice=turn.voice)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/conversation/local/{session_id}/greet")
def local_conversation_greet(session_id: str, selection: LocalConversationVoice, browser: Request) -> dict:
    require_local_conversation_browser(browser)
    try:
        return local_conversations.greet(session_id, selection.voice)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def dispatch_local_tool(session, call):
    local_conversations.check(session)
    if call["name"] == "get_creator_info":
        return get_creator_info()
    if call["name"] == "get_project_info":
        return get_project_info(session.engine, dialogue_model=conversation_llm.MODEL, voice=session.voice)
    if call["name"] == "look_at_scene":
        return camera_session.scene_snapshot()
    require_local_motion(session)
    kwargs = {"sessionId": session.motion_id, "callId": call["id"]}
    def authorize():
        require_local_motion(session)
        if not session.pending or not any(c is call for c in session.pending["calls"]):
            raise RuntimeError("Lokaler Auftrag wurde abgebrochen.")
    if call["name"] == "reset_robot":
        return reset_conversation_robot(ConversationRobotReset(**kwargs), origin="local-tool", authorize=authorize)
    return start_conversation_task(ConversationTaskRequest(**kwargs, instruction=call["args"]["instruction"]), authorize=authorize)


@app.post("/api/conversation/local/{session_id}/tool")
def local_conversation_tool(session_id: str, call: LocalConversationTool, browser: Request) -> dict:
    require_local_conversation_browser(browser)
    try:
        return local_conversations.execute(session_id, call.callId, call.announced, dispatch_local_tool)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/conversation/local/{session_id}/feedback")
def local_conversation_feedback(session_id: str, browser: Request, selection: LocalConversationVoice | None = None) -> dict:
    require_local_conversation_browser(browser)
    try:
        return local_conversations.feedback(session_id, {
            "motion": conversation_motion_status(), "task": task_status()}, voice=selection.voice if selection else None)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/conversation/local/{session_id}/continue")
def local_conversation_continue(session_id: str, browser: Request) -> dict:
    require_local_conversation_browser(browser)
    try:
        return local_conversations.finish(session_id)
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/conversation/greet")
async def conversation_greet(browser: Request) -> dict:
    require_local_conversation_browser(browser)
    try:
        return await run_in_threadpool(conversation_llm.greet)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/conversation/reply")
async def conversation_reply(request: ConversationRequest) -> dict:
    try:
        return await run_in_threadpool(conversation_llm.reply, request.text, request.previousResponseId)
    except (RuntimeError, TimeoutError, OSError, ValueError) as exc:
        logging.getLogger(__name__).exception("Conversation generation failed")
        raise HTTPException(status_code=503, detail=f"Antwortmodell fehlgeschlagen: {exc}") from exc


@app.post("/api/conversation/speak")
async def conversation_speak(request: SpeakRequest) -> Response:
    if request.engine == "piper":
        if not piper_voice_ready(request.voice):
            raise HTTPException(status_code=503, detail="Piper oder die gewählte Stimme ist nicht installiert.")
        worker = piper_worker
    else:
        if not TTS_PYTHON.is_file() or not TTS_MANIFEST.is_file():
            raise HTTPException(status_code=503, detail="Qwen3-TTS CustomVoice ist nicht installiert.")
        worker = tts_worker
    with tempfile.TemporaryDirectory(prefix="so101-tts-") as temp_dir:
        path = Path(temp_dir) / "speech.wav"
        try:
            await run_in_threadpool(worker.request, {"text": request.text, "speaker": request.speaker,
                                                     "voice": request.voice, "language": request.language, "path": str(path)})
            audio = path.read_bytes()
        except (RuntimeError, TimeoutError, OSError, ValueError) as exc:
            logging.getLogger(__name__).exception("TTS generation failed")
            raise HTTPException(status_code=503, detail=f"Sprachausgabe fehlgeschlagen: {exc}") from exc
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def require_local_browser_origin(request, call_next):
    origin = request.headers.get("origin")
    if request.url.path.startswith("/api/") and origin:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1", "localhost", "::1",
        }:
            return JSONResponse(
                status_code=403,
                content={"detail": "Nur lokale Browser dürfen diese API verwenden."},
            )
    return await call_next(request)


def static_reset_blocker() -> str | None:
    try:
        pose = json.loads(POSE_CONFIG.read_text())
        if not pose.get("automatic_travel_validated", False):
            return str(pose.get("automatic_travel_blocker") or
                       "Automatische Fahrt zur Startposition ist noch nicht validiert.")
        calibration = Path(pose["calibration_path"])
        if hashlib.sha256(calibration.read_bytes()).hexdigest() != pose["calibration_sha256"]:
            return "Die gespeicherte Startposition passt nicht zur aktuellen Kalibrierung."
        if not Path(pose["port"]).exists():
            return "Der gespeicherte Follower-Anschluss ist nicht verfügbar."
        if not FLUX_PYTHON.is_file() or not RESET_RUNNER.is_file():
            return "Der gemeinsame SO-101-Controller ist nicht installiert."
    except (OSError, ValueError, KeyError):
        return "Die gespeicherte Startposition ist nicht verfügbar."
    return None


def reset_blocker() -> str | None:
    if teleoperation_session.status()["occupied"]:
        return "Teleoperation belegt den Follower. Zuerst Teleoperation stoppen."
    if conversation_motion_status()["occupied"]:
        return "Gesprächsbewegung belegt den Follower. Zuerst Gespräch beenden."
    state, fault = reset_state()
    if state != "idle":
        return "Eine Fahrt zur Startposition oder ein überwachtes Halten läuft bereits."
    if torque_state()[0] != "idle":
        return "Drehmoment wird durch die UI gehalten oder geändert. Zuerst lösen."
    if fault:
        return f"Letzter Reset abgebrochen; Hardware prüfen: {fault}"
    return static_reset_blocker()


def teleop_blocker() -> str | None:
    if teleoperation_session.status()["occupied"]:
        return "Teleoperation läuft bereits."
    if reset_state()[0] != "idle" or _return_running:
        return "Startpositions-Controller belegt den Follower."
    if torque_state()[0] != "idle":
        return "Drehmoment-Controller belegt den Follower. Zuerst Drehmoment ausschalten."
    if conversation_motion_status()["occupied"]:
        return "Gesprächsbewegung belegt den Follower."
    task = task_status()
    if task and task["state"] in {"loading", "running", "stopping"}:
        return "Ein Modelllauf ist noch aktiv."
    if _policy_lock.locked():
        return "Modell- oder Robotersteuerung ist gerade beschäftigt."
    if not follower_port_available() or not LEADER_PORT.exists():
        return "Leader oder Follower ist nicht verbunden."
    if not FLUX_PYTHON.is_file() or not TELEOP_RUNNER.is_file():
        return "Teleoperations-Controller ist nicht installiert."
    return None


def reset_state() -> tuple[str, str | None]:
    global _reset_state, _reset_process, _reset_report_path, _reset_fault, _torque_verified_off
    with _reset_guard:
        if _reset_process is not None and _reset_process.poll() is not None:
            try:
                report = json.loads(_reset_report_path.read_text()) if _reset_report_path else {}
            except (OSError, ValueError):
                report = {}
            if report.get("outcome") == "holding_after_disconnect":
                _reset_fault = "Motor-Controller getrennt; Halteziel und Drehmoment waren beim Trennen bestätigt."
            elif report.get("outcome") != "released_after_hold":
                _reset_fault = report.get("cleanup_error") or report.get("error") or \
                    "Reset-Prozess endete unerwartet."
            else:
                _torque_verified_off = True
            _reset_process = None
            _reset_report_path = None
            _reset_state = "idle"
        return _reset_state, _reset_fault


def physical_holder_ready() -> bool:
    with _reset_guard:
        args = getattr(_reset_process, "args", None)
        return (_reset_state == "holding" and _reset_process is not None
                and _reset_process.poll() is None
                and isinstance(args, (list, tuple)) and len(args) >= 2
                and Path(args[1]).name == "ui_robot_holder.py")


def holder_supports_return() -> bool:
    if not physical_holder_ready():
        return False
    with _reset_guard:
        report_path = _reset_report_path
    try:
        report = json.loads(report_path.read_text()) if report_path else {}
    except (OSError, ValueError):
        return False
    return "return_to_start" in report.get("capabilities", [])


def torque_state() -> tuple[str, str | None]:
    global _torque_state, _torque_process, _torque_report_path, _torque_fault, _torque_verified_off
    with _torque_guard:
        if _torque_process is not None and _torque_process.poll() is not None:
            try:
                report = json.loads(_torque_report_path.read_text()) if _torque_report_path else {}
            except (OSError, ValueError):
                report = {}
            if report.get("outcome") != "torque_released":
                _torque_fault = report.get("cleanup_error") or report.get("error") or \
                    "Drehmoment-Halteprozess endete unerwartet."
            else:
                _torque_fault = None
                _torque_verified_off = True
            _torque_process = None
            _torque_report_path = None
            _torque_state = "idle"
        return _torque_state, _torque_fault


def get_model():
    global _model
    if _model is None:
        _model = load_model()
    return _model


def warm_asr_model() -> None:
    global _asr_loading, _asr_error
    try:
        with _model_lock:
            get_model()
    except Exception:
        _asr_error = "Qwen3-ASR konnte nicht geladen werden. Dienstprotokoll prüfen."
        logging.getLogger(__name__).exception("Qwen3-ASR warm-up failed")
    finally:
        _asr_loading = False


def start_asr_warmup() -> None:
    global _asr_loading, _asr_error
    if MODEL_PATH.is_dir() and torch.cuda.is_available() and _model is None and not _asr_loading:
        _asr_error = None
        _asr_loading = True
        threading.Thread(target=warm_asr_model, name="qwen-asr-warmup", daemon=True).start()


def recover_torque_reset_fault() -> None:
    """Keep an unresolved torque-on reset fault visible across UI restarts."""
    global _reset_fault
    reports = list((ROOT / "outputs").glob("ui-reset-*.json"))
    if not reports:
        return
    latest = max(reports, key=lambda path: path.stat().st_mtime)
    try:
        report = json.loads(latest.read_text())
        error = report.get("cleanup_error") or report.get("error") or ""
        if report.get("outcome") != "aborted" or "Motor health: torque=" not in error:
            return
        cleared = any(path.stat().st_mtime > latest.stat().st_mtime and
                      json.loads(path.read_text()).get("outcome") == "torque_off_verified"
                      for path in (ROOT / "outputs").glob("ui-torque-off-*.json"))
        if not cleared:
            _reset_fault = error
    except (OSError, ValueError):
        logging.getLogger(__name__).warning("Could not recover prior reset fault")


def task_status_unlocked(source: dict) -> dict:
    status = {key: source[key] for key in
              ("id", "model", "prompt", "state", "chunks", "actions",
               "startedAt", "endedAt", "message")}
    status.update({key: source.get(key, -1) for key in
                   ("generation", "inferenceGeneration", "executedGeneration")})
    return status


def task_status() -> dict | None:
    with _task_guard:
        source = _active_task or _last_task
        return task_status_unlocked(source) if source is not None else None


def decode_audio(source: Path, destination: Path) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", str(source), "-ac", "1", "-ar", "16000", "-t", "31",
                "-y", str(destination),
            ],
            check=True, capture_output=True, text=True, timeout=45,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=422, detail="Audio konnte nicht dekodiert werden.") from exc
    try:
        info = sf.info(str(destination))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail="Dekodiertes Audio ist ungültig.") from exc
    if not 0 < info.duration <= MAX_AUDIO_SECONDS:
        raise HTTPException(status_code=413, detail="Aufnahme muss zwischen 0 und 30 Sekunden lang sein.")


@app.get("/api/status")
def status() -> dict:
    model_installed = MODEL_PATH.is_dir()
    cuda_available = torch.cuda.is_available()
    installed = model_installed and cuda_available
    available = installed and _model is not None
    state, _ = reset_state()
    torque_mode, torque_fault = torque_state()
    conversation_motion = conversation_motion_status()
    teleop = teleoperation_session.status()
    teleop_message = teleop_blocker()
    torque_action = "off" if state == "holding" or torque_mode == "holding" or conversation_motion["occupied"] or teleop["occupied"] or not _torque_verified_off else "on"
    blocker = reset_blocker()
    task = task_status()
    with _reset_guard:
        return_running = _return_running
    return_blocker = ("Gesprächsbewegung belegt den Follower."
                      if conversation_motion["occupied"] else
                      "Der laufende Motor-Controller unterstützt die Rückfahrt noch nicht."
                      if state == "holding" and not holder_supports_return() else
                      static_reset_blocker())
    # Both warmup and prediction own the worker locks for a long time. Status
    # must stay responsive so it cannot starve heartbeats and stop requests.
    if _policy_lock.acquire(blocking=False):
        try:
            ready_model = policy_session.ready_model_id
            camera_model = camera_session.model_id
        finally:
            _policy_lock.release()
    else:
        ready_model = task["model"] if task and task["state"] in {"running", "stopping"} else None
        camera_model = ready_model
    return {
        "asrReady": available,
        "asrLoading": installed and _asr_loading,
        "robotConnected": state == "holding" or torque_mode == "holding" or conversation_motion["active"] or teleop["occupied"],
        "modelSession": ready_model,
        "cameraModel": camera_model,
        "resetAvailable": blocker is None,
        "resetRunning": state in {"starting", "releasing"} or return_running,
        "resetHolding": state == "holding",
        "returnAvailable": state == "holding" and holder_supports_return()
                           and not return_running and return_blocker is None,
        "returnRunning": return_running,
        "returnMessage": return_blocker or ("Der Modelllauf wird vor der Rückfahrt angehalten."
                                            if task and task["state"] in {"running", "stopping"} else
                                            "Rückfahrt zur Startposition ist verfügbar."),
        "physicalReady": not teleop["occupied"] and physical_holder_ready() and ready_model is not None
                         and camera_model == ready_model,
        "taskRun": task,
        "teleoperation": {**teleop, "available": teleop_message is None,
                           "blocker": teleop_message},
        "torqueHolding": torque_mode == "holding",
        "torqueRunning": torque_mode in {"starting", "releasing"},
        "torqueAction": torque_action,
        "torqueAvailable": (state in {"idle", "holding"} and torque_mode in {"idle", "holding"}
                            and not teleop["occupied"]
                            and TORQUE_RUNNER.is_file() and FLUX_PYTHON.is_file()
                            and (torque_action == "off" or static_reset_blocker() is None)),
        "torqueMessage": torque_fault or ("Teleoperation läuft; Drehmoment aus stoppt sie zuerst."
                                    if teleop["occupied"] else
                                    "Gesprächsbewegung hält den Follower."
                                    if conversation_motion["occupied"] else
                                    "Drehmoment wird überwacht gehalten."
                                    if torque_mode == "holding" else
                                    "Drehmoment aus wurde bestätigt."
                                    if _torque_verified_off else
                                    "Motorzustand unbekannt: zuerst Drehmoment ausschalten und prüfen."),
        "message": blocker or "Reset-Controller ist bereit.",
        "asrMessage": None if available else (
            "Qwen3-ASR-Modell fehlt." if not model_installed else
            "CUDA ist für Qwen3-ASR nicht verfügbar." if not cuda_available else
            "Qwen3-ASR wird geladen …" if _asr_loading else
            _asr_error or "Qwen3-ASR wurde noch nicht geladen."
        ),
    }


@app.get("/api/models")
def model_status() -> dict:
    return {"models": available_models(cuda_available=torch.cuda.is_available())}


@app.post("/api/models/{model_id}/select")
async def select_model(model_id: str) -> dict:
    """Unload the old worker and finish loading the selected model immediately."""
    selected = next((model for model in available_models(
        cuda_available=torch.cuda.is_available()) if model["id"] == model_id), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Unbekanntes Modell.")
    if not selected["available"]:
        raise HTTPException(status_code=503, detail=selected["message"])
    if reset_state()[0] not in {"idle", "holding"}:
        raise HTTPException(status_code=409, detail="Während des Hardware-Resets ist kein Modellwechsel möglich.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft bereits.")
    try:
        require_no_physical_client()
        if policy_session.model_id not in (None, model_id):
            await run_in_threadpool(policy_session.stop)
        camera = await run_in_threadpool(camera_session.select, model_id)
        loaded = await run_in_threadpool(policy_session.preload, model_id)
        return {**camera, "modelReady": loaded["ready"]}
    except PhysicalCameraLeaseBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="Modellladen hat das Zeitlimit überschritten.") from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _policy_lock.release()


@app.post("/api/cameras/{model_id}/select")
async def select_camera_model(model_id: str) -> dict:
    if model_id not in {"molmoact2", "conversation"}:
        raise HTTPException(status_code=404, detail="Unbekanntes Kameraprofil.")
    if reset_state()[0] not in {"idle", "holding"}:
        raise HTTPException(status_code=409, detail="Während des Hardware-Resets sind Kameras gesperrt.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft bereits.")
    try:
        if camera_session.model_id != model_id:
            require_no_physical_client()
        if policy_session.model_id not in (None, model_id):
            if model_id == "conversation":
                raise HTTPException(status_code=409, detail="Das geladene Modell nutzt ein anderes Kameraprofil.")
            await run_in_threadpool(policy_session.stop)
        return await run_in_threadpool(camera_session.select, model_id)
    except PhysicalCameraLeaseBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _policy_lock.release()


@app.get("/api/cameras/{model_id}/preview")
async def camera_preview(model_id: str) -> dict:
    if model_id not in {"molmoact2", "conversation"}:
        raise HTTPException(status_code=404, detail="Unbekanntes Kameraprofil.")
    try:
        return await run_in_threadpool(camera_session.preview, model_id)
    except (RuntimeError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/cameras/{model_id}/reload")
async def reload_camera_model(model_id: str) -> dict:
    """Restart only the camera worker while keeping the policy worker loaded."""
    if model_id not in {"molmoact2", "conversation"}:
        raise HTTPException(status_code=404, detail="Unbekanntes Kameraprofil.")
    if reset_state()[0] not in {"idle", "holding"}:
        raise HTTPException(status_code=409, detail="Während des Hardware-Resets sind Kameras gesperrt.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft bereits.")
    try:
        if policy_session.model_id not in (None, model_id):
            raise HTTPException(status_code=409, detail="Das geladene Modell nutzt ein anderes Kameraprofil.")
        require_no_physical_client()
        return await run_in_threadpool(camera_session.restart, model_id)
    except PhysicalCameraLeaseBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _policy_lock.release()


@app.post("/api/cameras/{model_id}/insta360-view")
async def set_insta360_camera_view(model_id: str, request: Insta360ViewRequest) -> dict:
    if model_id not in {"molmoact2", "conversation"}:
        raise HTTPException(status_code=404, detail="Dieses Kameraprofil nutzt keine Insta360.")
    if reset_state()[0] not in {"idle", "holding"}:
        raise HTTPException(status_code=409, detail="Während des Hardware-Resets sind Kameras gesperrt.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Lauf zuerst stoppen, bevor der Kameraausschnitt geändert wird.")
    try:
        return await run_in_threadpool(camera_session.set_insta360_view, model_id, request.model_dump())
    except PhysicalCameraLeaseBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, ValueError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _policy_lock.release()


@app.post("/api/cameras/{model_id}/{role}/brightness")
async def set_camera_brightness(model_id: str, role: str, request: CameraBrightnessRequest) -> dict:
    roles = {"conversation": {"cam0", "cam1", "wrist"}, "molmoact2": {"cam0", "cam1", "wrist"}}
    if role not in roles.get(model_id, set()):
        raise HTTPException(status_code=404, detail="Unbekannte Kamera.")
    if reset_state()[0] not in {"idle", "holding"}:
        raise HTTPException(status_code=409, detail="Während des Hardware-Resets sind Kameras gesperrt.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Lauf zuerst stoppen, bevor die Helligkeit geändert wird.")
    try:
        return await run_in_threadpool(camera_session.set_camera_brightness, model_id, role, request.value)
    except PhysicalCameraLeaseBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _policy_lock.release()


@app.post("/api/cameras/{model_id}/{role}/exposure")
async def set_camera_exposure(model_id: str, role: str, request: CameraExposureRequest) -> dict:
    roles = {"conversation": {"cam0", "cam1", "wrist"}, "molmoact2": {"cam0", "cam1", "wrist"}}
    if role not in roles.get(model_id, set()):
        raise HTTPException(status_code=404, detail="Unbekannte Kamera.")
    if reset_state()[0] not in {"idle", "holding"}:
        raise HTTPException(status_code=409, detail="Während des Hardware-Resets sind Kameras gesperrt.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Lauf zuerst stoppen, bevor die Belichtung geändert wird.")
    try:
        return await run_in_threadpool(camera_session.set_camera_exposure, model_id, role, request.value)
    except PhysicalCameraLeaseBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _policy_lock.release()


@app.post("/api/models/{model_id}/infer")
async def model_infer(model_id: str, request: ModelRequest) -> dict:
    if model_id not in {"molmoact2"}:
        raise HTTPException(status_code=404, detail="Unbekanntes Modell.")
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Bitte einen Befehl eingeben.")
    if reset_state()[0] not in {"idle", "holding"}:
        raise HTTPException(status_code=409, detail="Während der Fahrt zur Startposition ist keine Inferenz möglich.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft bereits.")
    try:
        require_no_physical_client()
        with camera_switch_guard():
            if request.liveCamera:
                capture = await run_in_threadpool(camera_session.capture, model_id)
                result = await run_in_threadpool(run_model_inference, model_id, prompt,
                                                 camera_npz=capture["path"])
                return {**result, "cameraCapture": {
                    "model": model_id, "geometry": capture["geometry"],
                    "frames": capture["frames"], "capturedAt": capture["capturedAt"],
                }}
            return await run_in_threadpool(run_model_inference, model_id, prompt)
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="Modelllauf hat das Zeitlimit überschritten.") from exc
    except PhysicalCameraLeaseBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _policy_lock.release()


def holder_command(command: dict, *, timeout_s: float = 90) -> dict:
    """One request to the process that exclusively owns the follower serial bus."""
    with _holder_command_lock:
        with _reset_guard:
            process = _reset_process
            args = getattr(process, "args", None)
            if (_reset_state != "holding" or process is None or process.poll() is not None
                    or not isinstance(args, (list, tuple)) or len(args) < 2
                    or Path(args[1]).name != "ui_robot_holder.py"):
                raise RuntimeError("Startposition muss vom neuen UI-Controller überwacht gehalten werden.")
        reply_path = ROOT / "outputs" / f"ui-robot-reply-{uuid.uuid4().hex}.json"
        command = {**command, "reply_path": str(reply_path)}
        try:
            # Action arrays travel by file, so each pipe command stays below
            # PIPE_BUF and cannot interleave with an operator release byte.
            encoded = (json.dumps(command, ensure_ascii=False) + "\n").encode()
            if len(encoded) > 4096 or os.write(process.stdin.fileno(), encoded) != len(encoded):
                raise RuntimeError("Motor-Controller-Befehl konnte nicht atomar gesendet werden.")
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if reply_path.is_file():
                    result = json.loads(reply_path.read_text())
                    if result.get("status") == "rejected":
                        raise RuntimeError(result.get("error") or "Motor-Controller hat den Aktionsblock abgelehnt.")
                    return result
                if process.poll() is not None:
                    raise RuntimeError("Motor-Controller endete vor der Bestätigung.")
                time.sleep(0.05)
            raise TimeoutError("Motor-Controller antwortete nicht; Drehmomentzustand prüfen.")
        finally:
            reply_path.unlink(missing_ok=True)


def conversation_holder_command(session_id: str, command: dict, *, timeout_s: float = 90) -> dict:
    """Send one task request to the process that already owns the conversation arm."""
    with _holder_command_lock:
        with _conversation_motion_guard:
            process = _conversation_motion_process
            if (_conversation_motion_id != session_id or process is None
                    or process.poll() is not None or process.stdin is None):
                raise RuntimeError("Gesprächs-Controller hält den Follower nicht mehr.")
            reply_path = ROOT / "outputs" / f"ui-robot-reply-{uuid.uuid4().hex}.json"
            encoded = (json.dumps({**command, "reply_path": str(reply_path)},
                                  ensure_ascii=False) + "\n").encode()
            if len(encoded) > 4096 or os.write(process.stdin.fileno(), encoded) != len(encoded):
                raise RuntimeError("Gesprächs-Controller-Befehl konnte nicht atomar gesendet werden.")
        try:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if reply_path.is_file():
                    result = json.loads(reply_path.read_text())
                    if result.get("status") == "rejected":
                        raise RuntimeError(result.get("error") or "Gesprächs-Controller lehnte die Aufgabe ab.")
                    return result
                if process.poll() is not None:
                    raise RuntimeError("Gesprächs-Controller endete vor der Bestätigung.")
                time.sleep(0.05)
            raise TimeoutError("Gesprächs-Controller antwortete nicht; Drehmomentzustand prüfen.")
        finally:
            reply_path.unlink(missing_ok=True)


def _write_task_epoch(run: dict) -> None:
    path = run["epochPath"]
    temporary = path.with_suffix(".tmp")
    temporary.write_text(str(run["generation"]))
    temporary.replace(path)


def _run_generation(run: dict) -> tuple[int, str, bool]:
    with _task_guard:
        return run["generation"], run["prompt"], run["stop"].is_set()


def physical_task_loop(run: dict) -> None:
    """Reobserve and replan until operator Stop or a controller failure."""
    global _active_task, _last_task
    outcome, message = "stopped", "Durch Stopp angehalten; Drehmoment wird gehalten."
    conversation_id = run.get("conversationSessionId")
    command_owner = (lambda command: conversation_holder_command(conversation_id, command)) \
        if conversation_id else holder_command
    task_activated = False
    try:
        if conversation_id:
            policy_session.preload("molmoact2")
            if run["stop"].is_set():
                return
            camera_session.select("molmoact2")
            if run["stop"].is_set():
                return
        command_owner({"op": "task_active"})
        task_activated = True
        if conversation_id:
            with _task_guard:
                if not run["stop"].is_set():
                    run["state"] = "running"
                    run["message"] = "MolmoAct2 läuft mit frischen Kamerabildern."
        while True:
            generation, prompt, stopped = _run_generation(run)
            if stopped:
                break
            observation_path = ROOT / "outputs" / f"ui-robot-observation-{uuid.uuid4().hex}.npz"
            actions_path = ROOT / "outputs" / f"ui-robot-actions-{uuid.uuid4().hex}.json"
            try:
                observed = command_owner({"op": "snapshot", "model": run["model"],
                                           "observation_path": str(observation_path)})
                if (observed.get("status") != "observed" or observed.get("model") != run["model"]
                        or observed.get("observation_path") != str(observation_path)
                        or not observation_path.is_file()):
                    raise RuntimeError("Motor-Controller lieferte keine gültige Live-Beobachtung.")
                with _task_guard:
                    if run["stop"].is_set() or run["generation"] != generation:
                        continue
                    run["inferenceGeneration"] = generation
                try:
                    prediction = predict_physical_chunk(run["model"], prompt,
                                                        observation_npz=str(observation_path),
                                                        state=observed["state"])
                except (RuntimeError, OSError, TimeoutError):
                    if run["stop"].is_set():
                        break
                    raise
                if run["stop"].is_set() or _run_generation(run)[0] != generation:
                    continue
                actions_path.write_text(json.dumps(prediction["actions"], allow_nan=False))
                execution = command_owner({"op": "execute", "model": run["model"],
                                            "observed_state": observed["state"],
                                            "actions_path": str(actions_path),
                                            "epoch_path": str(run["epochPath"]),
                                            "epoch": generation})
                if execution.get("status") not in {"executed", "stopped"}:
                    raise RuntimeError("Aktionsblock wurde vorzeitig beendet.")
                with _task_guard:
                    run["actions"] += execution.get("executedActions", 0)
                    if execution.get("executedActions", 0) > 0:
                        run["executedGeneration"] = generation
                    if execution["status"] == "executed":
                        run["chunks"] += 1
                    run["message"] = f'{run["chunks"]} Blöcke, {run["actions"]} Aktionen ausgeführt.'
            finally:
                observation_path.unlink(missing_ok=True)
                actions_path.unlink(missing_ok=True)
    except BaseException as exc:
        outcome, message = "failed", f"{type(exc).__name__}: {exc}"
        logging.getLogger(__name__).exception("Physical task run failed")
    finally:
        if task_activated:
            try:
                inactive = command_owner({"op": "task_inactive"})
                if conversation_id:
                    run["speechGripperAvailable"] = inactive.get("speechGripperAvailable", False)
            except (RuntimeError, TimeoutError, OSError):
                logging.getLogger(__name__).exception("Could not end active task hold")
                outcome, message = "failed", "Follower-Halt nach Aufgabe nicht bestätigt; Zustand prüfen."
        with _task_guard:
            run["state"] = outcome
            run["message"] = message
            run["endedAt"] = time.time()
            _last_task = run
            if _active_task is run:
                _active_task = None
        run["epochPath"].unlink(missing_ok=True)
        _policy_lock.release()


def request_physical_task_stop() -> dict | None:
    """Invalidate in-flight actions before another command may move the arm."""
    with _task_guard:
        if _active_task is None:
            return None
        run = _active_task
        if not run["stop"].is_set():
            run["generation"] += 1
            run["stop"].set()
            _write_task_epoch(run)
        run["state"] = "stopping"
        run["message"] = "Stopp angefordert; Motor-Controller hält die gemessene Position."
        return task_status_unlocked(run)


def wait_for_stopped_task(*, timeout_s: float = 45, interrupt_after_s: float = 5) -> None:
    """Wait for the holder's measured hold; abort a stalled policy prediction."""
    started = time.monotonic()
    deadline = started + timeout_s
    interrupted = False
    while time.monotonic() < deadline:
        if _policy_lock.acquire(timeout=min(0.2, max(0.0, deadline - time.monotonic()))):
            return
        if not interrupted and time.monotonic() - started >= interrupt_after_s:
            with _task_guard:
                task_active = _active_task is not None
            if task_active:
                policy_session.interrupt_active_request()
                interrupted = True
    raise TimeoutError("Modelllauf wurde nicht vollständig angehalten; Rückfahrt nicht gestartet.")


@app.post("/api/models/{model_id}/task")
async def execute_model_task(model_id: str, request: ModelRequest, browser: Request) -> dict:
    global _active_task
    if browser.headers.get("x-so101-execute") != "operator-ptt":
        raise HTTPException(status_code=403, detail="Motorlauf erfordert eine ausdrückliche Push-to-Talk-Betätigung.")
    if model_id not in {"molmoact2"}:
        raise HTTPException(status_code=404, detail="Unbekanntes Modell.")
    if not request.liveCamera:
        raise HTTPException(status_code=422, detail="Physische Inferenz benötigt Live-Kameras.")
    if conversation_motion_status()["occupied"]:
        raise HTTPException(status_code=409, detail="Gesprächsbewegung belegt den Follower.")
    if teleoperation_session.status()["occupied"]:
        raise HTTPException(status_code=409, detail="Teleoperation belegt den Follower.")
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Bitte einen Befehl eingeben.")
    if not physical_holder_ready():
        raise HTTPException(status_code=409, detail="Zuerst Startposition mit dem aktuellen UI-Controller anfahren.")
    with _reset_guard:
        if _return_running:
            raise HTTPException(status_code=409, detail="Rückfahrt zur Startposition läuft bereits.")
        with _task_guard:
            if _active_task is not None:
                if _active_task["model"] != model_id or _active_task["stop"].is_set():
                    raise HTTPException(status_code=409, detail="Zuerst laufende Aufgabe stoppen.")
                _active_task["generation"] += 1
                _active_task["prompt"] = prompt
                _write_task_epoch(_active_task)
                _active_task["message"] = "Neue Anweisung übernommen; alter Aktionsblock wird verworfen."
                return {"status": "updated", "taskRun": task_status_unlocked(_active_task)}
    if policy_session.ready_model_id != model_id or camera_session.model_id != model_id:
        raise HTTPException(status_code=409, detail="Ausgewähltes Modell und Kameraprofil sind nicht geladen.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft bereits.")
    run_id = uuid.uuid4().hex
    run = {"id": run_id, "model": model_id, "prompt": prompt, "state": "running",
           "chunks": 0, "actions": 0, "startedAt": time.time(), "endedAt": None,
           "message": "Live-Aufgabe gestartet.",
           "generation": 0, "inferenceGeneration": -1, "executedGeneration": -1,
           "stop": threading.Event(),
           "epochPath": ROOT / "outputs" / f"ui-robot-epoch-{run_id}.txt"}
    try:
        with _reset_guard:
            if _return_running:
                raise RuntimeError("Rückfahrt zur Startposition läuft bereits.")
            with _task_guard:
                if _active_task is not None:
                    raise RuntimeError("Ein Modelllauf läuft bereits.")
                _write_task_epoch(run)
                _active_task = run
        threading.Thread(target=physical_task_loop, args=(run,),
                         name=f"physical-{model_id}-{run_id[:8]}", daemon=True).start()
        return {"status": "started", "taskRun": task_status_unlocked(run)}
    except BaseException as exc:
        with _task_guard:
            if _active_task is run:
                _active_task = None
        run["epochPath"].unlink(missing_ok=True)
        _policy_lock.release()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/task/stop")
async def stop_physical_task(browser: Request) -> dict:
    if browser.headers.get("x-so101-stop") != "operator-click":
        raise HTTPException(status_code=403, detail="Stopp erfordert eine ausdrückliche UI-Betätigung.")
    task = request_physical_task_stop()
    if task is None:
        raise HTTPException(status_code=409, detail="Keine laufende Aufgabe.")
    return {"status": "stopping", "taskRun": task}


@app.get("/api/task/status")
def physical_task_status() -> dict:
    """Read task progress without waiting for a policy model load."""
    return {"taskRun": task_status()}


@app.delete("/api/session")
async def stop_model_session() -> dict:
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft noch.")
    try:
        try:
            require_no_physical_client()
            await run_in_threadpool(policy_session.stop)
            await run_in_threadpool(camera_session.stop)
        except PhysicalCameraLeaseBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "stopped"}
    finally:
        _policy_lock.release()


@app.delete("/api/models/current")
async def unload_current_model() -> dict:
    """Free the policy worker without closing the camera preview or robot holder."""
    if reset_state()[0] not in {"idle", "holding"}:
        raise HTTPException(status_code=409, detail="Während des Hardware-Resets ist kein Entladen möglich.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft noch.")
    try:
        try:
            await run_in_threadpool(policy_session.stop)
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "unloaded"}
    finally:
        _policy_lock.release()


@app.post("/api/transcribe")
async def transcribe_upload(audio: UploadFile = File(...),
                            language: Literal["German", "English", "Auto"] = Form("German")) -> dict:
    if not MODEL_PATH.is_dir() or not torch.cuda.is_available():
        raise HTTPException(status_code=503, detail="Qwen3-ASR oder CUDA ist nicht verfügbar.")

    with tempfile.TemporaryDirectory(prefix="so101-ptt-") as temp_dir:
        source = Path(temp_dir) / "recording"
        decoded = Path(temp_dir) / "recording.wav"
        total = 0
        with source.open("wb") as output:
            while chunk := await audio.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Audiodatei ist zu groß.")
                output.write(chunk)
        await audio.close()
        if total == 0:
            raise HTTPException(status_code=422, detail="Leere Aufnahme.")
        await run_in_threadpool(decode_audio, source, decoded)
        try:
            # One model instance, one inference at a time. The first request
            # loads the local weights; later PTT recordings reuse them.
            def infer() -> dict:
                with _model_lock:
                    return transcribe(get_model(), decoded, language)

            return await run_in_threadpool(infer)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Qwen3-ASR-Transkription fehlgeschlagen.") from exc


def start_reset_process(report_path: Path) -> subprocess.Popen:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.with_suffix(".log").open("w") as log:
        process = subprocess.Popen(
            [str(FLUX_PYTHON), str(RESET_RUNNER), "--report", str(report_path)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
            text=True,
        )
    while True:
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text())
            except ValueError:
                report = {}
            if report.get("outcome") == "reset_pose_holding_torque":
                return process
            if report.get("outcome") == "aborted":
                process.wait()
                raise RuntimeError(report.get("cleanup_error") or report.get("error") or
                                   "Reset abgebrochen.")
        if process.poll() is not None:
            raise RuntimeError(f"Reset-Prozess endete vor dem Halten (exit={process.returncode}).")
        time.sleep(0.1)


def release_reset_process(process: subprocess.Popen, report_path: Path) -> dict:
    if process.poll() is None:
        try:
            os.write(process.stdin.fileno(), b"r\n")
            process.stdin.close()
        except (OSError, BrokenPipeError):
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Reset-Controller reagiert nicht; Hardware-Stromabschaltung verwenden.") from exc
    try:
        report = json.loads(report_path.read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError("Reset-Controller hat keinen Abschlussbericht geschrieben.") from exc
    if process.returncode or report.get("outcome") != "released_after_hold":
        raise RuntimeError(report.get("cleanup_error") or report.get("error") or
                           "Drehmoment-Abschaltung wurde nicht bestätigt.")
    return {"status": "released", "message": "Drehmoment ausgeschaltet und bestätigt."}


@app.post("/api/teleoperation/start")
async def start_teleoperation(request: Request) -> dict:
    if request.headers.get("x-so101-teleop") != "operator-click":
        raise HTTPException(status_code=403, detail="Teleoperation erfordert einen ausdrücklichen UI-Klick.")
    blocker = teleop_blocker()
    if blocker:
        raise HTTPException(status_code=409, detail=blocker)
    camera_warning = None
    try:
        camera_model = camera_session.model_id
        if camera_model is None:
            camera_warning = "Keine Live-Kameras aktiv."
        else:
            preview = await run_in_threadpool(camera_session.preview, camera_model)
            if (time.time() - float(preview.get("capturedAt", 0)) > 3
                    or len(preview.get("previews", {})) < 2):
                camera_warning = "Live-Kamerabilder sind nicht frisch oder unvollständig."
            else:
                sources = preview.get("cameraSources", {})
                if camera_model == "molmoact2" and sources.get("cam0") == sources.get("cam1"):
                    camera_warning = "Overhead und X5 liefern keine zwei unabhängigen Livebilder."
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        camera_warning = f"Live-Kamerabilder nicht verfügbar: {exc}"
    try:
        blocker = teleop_blocker()
        if blocker:
            raise RuntimeError(blocker)
        result = await run_in_threadpool(teleoperation_session.start)
        if camera_warning:
            result["warning"] = camera_warning
            result["message"] = (f"{result.get('message') or 'Teleoperation läuft.'} "
                                 f"Warnung: {camera_warning} Kameras sind für Teleoperation optional.")
        return result
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/teleoperation/stop")
async def stop_teleoperation(request: Request) -> dict:
    if request.headers.get("x-so101-teleop") != "operator-click":
        raise HTTPException(status_code=403, detail="Teleoperations-Stopp erfordert einen ausdrücklichen UI-Klick.")
    try:
        return await run_in_threadpool(teleoperation_session.stop)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/reset")
async def reset(request: Request) -> dict:
    global _reset_state, _reset_process, _reset_report_path, _reset_fault, _torque_verified_off
    if request.headers.get("x-so101-reset") != "operator-click":
        raise HTTPException(status_code=403, detail="Reset erfordert eine ausdrückliche UI-Betätigung.")
    blocker = reset_blocker()
    if blocker:
        raise HTTPException(status_code=409, detail=blocker)
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft noch.")
    try:
        if torque_state()[0] != "idle":
            raise HTTPException(status_code=409, detail="Drehmoment wird bereits gehalten oder geändert.")
        with _reset_guard:
            if _reset_state != "idle":
                raise HTTPException(status_code=409, detail="Eine Fahrt läuft bereits.")
            if teleoperation_session.status()["occupied"]:
                raise HTTPException(status_code=409, detail="Teleoperation belegt den Follower.")
            _reset_state = "starting"
        _torque_verified_off = False
    finally:
        _policy_lock.release()
    try:
        # Re-check after reserving the reset slot. Dynamic serial and motor
        # checks occur again inside flux3_ui_reset before torque changes.
        blocker = static_reset_blocker()
        if blocker:
            raise HTTPException(status_code=409, detail=blocker)
        report_path = ROOT / "outputs" / f"ui-reset-{uuid.uuid4().hex}.json"
        process = await run_in_threadpool(start_reset_process, report_path)
        with _reset_guard:
            _reset_process = process
            _reset_report_path = report_path
            _reset_state = "holding"
        return {"status": "holding", "message": "Startposition erreicht und überwacht gehalten."}
    except BaseException as exc:
        with _reset_guard:
            _reset_state = "idle"
            if isinstance(exc, RuntimeError):
                _reset_fault = str(exc)
        if isinstance(exc, RuntimeError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise


@app.post("/api/reset/return")
async def return_to_start(request: Request) -> dict:
    """Return through the current Follower owner, leaving its torque hold active."""
    global _return_running
    if request.headers.get("x-so101-reset") != "operator-click":
        raise HTTPException(status_code=403, detail="Rückfahrt erfordert eine ausdrückliche UI-Betätigung.")
    if conversation_motion_status()["occupied"] or not holder_supports_return():
        raise HTTPException(status_code=409, detail="Kein geeigneter UI-Motor-Controller hält den Follower.")
    blocker = static_reset_blocker()
    if blocker:
        raise HTTPException(status_code=409, detail=blocker)
    with _reset_guard:
        if _return_running:
            raise HTTPException(status_code=409, detail="Rückfahrt läuft bereits.")
        _return_running = True
    policy_owned = False
    try:
        task = request_physical_task_stop()
        if task is not None:
            await run_in_threadpool(wait_for_stopped_task)
            policy_owned = True
        else:
            policy_owned = _policy_lock.acquire(blocking=False)
            if not policy_owned:
                raise HTTPException(status_code=409, detail="Modellwechsel läuft; Rückfahrt noch nicht verfügbar.")
        with _task_guard:
            if _active_task is not None:
                raise RuntimeError("Modelllauf wurde nicht vollständig angehalten.")
        if not holder_supports_return():
            raise RuntimeError("Motor-Controller hält den Follower nicht mehr für die Rückfahrt.")
        result = await run_in_threadpool(holder_command, {"op": "return_to_start"}, timeout_s=150)
        if result.get("status") != "returned":
            raise RuntimeError("Motor-Controller hat die Rückfahrt nicht bestätigt.")
        return {"status": "returned", "message": "Startposition erreicht; Drehmoment bleibt eingeschaltet.",
                "measuredAfter": result["measured_after"]}
    except (RuntimeError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        with _reset_guard:
            _return_running = False
        if policy_owned:
            _policy_lock.release()


@app.post("/api/reset/release")
async def release_reset(request: Request) -> dict:
    global _reset_state, _reset_process, _reset_report_path, _reset_fault, _torque_verified_off
    if request.headers.get("x-so101-reset") != "operator-click":
        raise HTTPException(status_code=403, detail="Lösen erfordert eine ausdrückliche UI-Betätigung.")
    with _reset_guard:
        if _reset_state != "holding" or _reset_process is None or _reset_report_path is None:
            raise HTTPException(status_code=409, detail="Es wird keine Startposition gehalten.")
        process, report_path = _reset_process, _reset_report_path
        _reset_state = "releasing"
    try:
        result = await run_in_threadpool(release_reset_process, process, report_path)
        with _reset_guard:
            _reset_process = None
            _reset_report_path = None
            _reset_state = "idle"
        _torque_verified_off = True
        return result
    except RuntimeError as exc:
        with _reset_guard:
            if process.poll() is None:
                _reset_state = "holding"
            else:
                _reset_process = None
                _reset_report_path = None
                _reset_state = "idle"
                _reset_fault = str(exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def start_torque_process(report_path: Path) -> subprocess.Popen:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.with_suffix(".log").open("w") as log:
        process = subprocess.Popen(
            [str(FLUX_PYTHON), str(TORQUE_RUNNER), "--report", str(report_path)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
            text=True,
        )
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text())
            except ValueError:
                report = {}
            if report.get("outcome") == "torque_holding":
                return process
            if report.get("outcome") == "aborted":
                process.wait()
                raise RuntimeError(report.get("cleanup_error") or report.get("error") or
                                   "Drehmoment konnte nicht aktiviert werden.")
        if process.poll() is not None:
            raise RuntimeError(f"Drehmoment-Prozess endete vor der Haltebestätigung (exit={process.returncode}).")
        time.sleep(0.1)
    process.terminate()
    process.wait(timeout=10)
    raise TimeoutError("Drehmoment-Haltebestätigung blieb aus.")


def release_torque_process(process: subprocess.Popen, report_path: Path) -> dict:
    if process.poll() is None:
        try:
            process.stdin.write("r\n")
            process.stdin.flush()
            process.stdin.close()
        except (OSError, BrokenPipeError):
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Drehmoment-Controller reagiert nicht; Hardware-Stromabschaltung verwenden.") from exc
    try:
        report = json.loads(report_path.read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError("Drehmoment-Controller hat keinen Abschlussbericht geschrieben.") from exc
    if process.returncode or report.get("outcome") != "torque_released":
        raise RuntimeError(report.get("cleanup_error") or report.get("error") or
                           "Drehmoment-Abschaltung wurde nicht bestätigt.")
    return {"status": "off", "message": "Drehmoment ausgeschaltet und bestätigt."}


def turn_off_unmanaged(report_path: Path) -> dict:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.with_suffix(".log").open("w") as log:
        process = subprocess.run(
            [str(FLUX_PYTHON), str(TORQUE_RUNNER), "--report", str(report_path), "--off-once"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            timeout=20,
        )
    try:
        report = json.loads(report_path.read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError("Drehmoment-Abschaltung hat keinen Ergebnisbericht geschrieben.") from exc
    if process.returncode or report.get("outcome") != "torque_off_verified":
        raise RuntimeError(report.get("error") or report.get("cleanup_error") or
                           "Drehmoment-Abschaltung wurde nicht bestätigt.")
    return {"status": "off", "message": "Drehmoment ausgeschaltet und bestätigt.",
            "before": report["before"], "after": report["after"]}


@app.post("/api/torque/on")
async def torque_on(request: Request) -> dict:
    global _torque_state, _torque_process, _torque_report_path, _torque_fault, _torque_verified_off
    if request.headers.get("x-so101-torque") != "operator-click":
        raise HTTPException(status_code=403, detail="Drehmoment erfordert eine ausdrückliche UI-Betätigung.")
    if reset_state()[0] != "idle":
        raise HTTPException(status_code=409, detail="Während Startpositionsfahrt oder Halten ist Drehmoment bereits belegt.")
    if conversation_motion_status()["occupied"]:
        raise HTTPException(status_code=409, detail="Gesprächsbewegung hält den Follower bereits.")
    if teleoperation_session.status()["occupied"]:
        raise HTTPException(status_code=409, detail="Teleoperation hält den Follower bereits.")
    blocker = static_reset_blocker()
    if blocker:
        raise HTTPException(status_code=409, detail=blocker)
    if not TORQUE_RUNNER.is_file():
        raise HTTPException(status_code=409, detail="Drehmoment-Controller ist nicht installiert.")
    if not _policy_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Modelllauf läuft noch.")
    try:
        if reset_state()[0] != "idle":
            raise HTTPException(status_code=409, detail="Startpositions-Controller ist aktiv.")
        with _torque_guard:
            if _torque_state != "idle" or _torque_process is not None:
                raise HTTPException(status_code=409, detail="Drehmoment wird bereits gehalten oder geändert.")
            _torque_state = "starting"
        report_path = ROOT / "outputs" / f"ui-torque-{uuid.uuid4().hex}.json"
        process = await run_in_threadpool(start_torque_process, report_path)
        with _torque_guard:
            _torque_process = process
            _torque_report_path = report_path
            _torque_state = "holding"
            _torque_fault = None
        _torque_verified_off = False
        return {"status": "holding", "message": "Aktuelle Pose wird mit Drehmoment überwacht gehalten."}
    except BaseException as exc:
        with _torque_guard:
            _torque_state = "idle"
            _torque_fault = str(exc)
        _torque_verified_off = False
        if isinstance(exc, (RuntimeError, TimeoutError, OSError)):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise
    finally:
        _policy_lock.release()


@app.post("/api/torque/off")
async def torque_off(request: Request) -> dict:
    global _torque_state, _torque_process, _torque_report_path, _torque_fault, _reset_fault, _torque_verified_off
    global _conversation_motion_process, _conversation_motion_report, _conversation_motion_id
    global _conversation_motion_return_requested
    if request.headers.get("x-so101-torque") != "operator-click":
        raise HTTPException(status_code=403, detail="Drehmoment erfordert eine ausdrückliche UI-Betätigung.")
    if teleoperation_session.status()["occupied"]:
        try:
            await run_in_threadpool(teleoperation_session.stop)
        except (RuntimeError, OSError) as exc:
            if teleoperation_session.status()["occupied"]:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
    motion = conversation_motion_status()
    if motion["occupied"]:
        try:
            await run_in_threadpool(stop_conversation_motion, motion["sessionId"])
        except (RuntimeError, OSError) as exc:
            # An explicit torque-off command may still proceed after a dead
            # motion worker; the torque utility must read back all six motors.
            with _conversation_motion_guard:
                process = _conversation_motion_process
            if process is not None and process.poll() is None:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
    if reset_state()[0] != "idle":
        raise HTTPException(status_code=409, detail="Startpositions-Controller ist aktiv; dort Drehmoment lösen.")
    if not TORQUE_RUNNER.is_file() or not FLUX_PYTHON.is_file():
        raise HTTPException(status_code=409, detail="Drehmoment-Controller ist nicht installiert.")
    with _torque_guard:
        if _torque_state not in {"idle", "holding"}:
            raise HTTPException(status_code=409, detail="Drehmoment wird bereits geändert.")
        process, report_path = _torque_process, _torque_report_path
        _torque_state = "releasing"
    try:
        if process is not None and report_path is not None:
            result = await run_in_threadpool(release_torque_process, process, report_path)
        else:
            report_path = ROOT / "outputs" / f"ui-torque-off-{uuid.uuid4().hex}.json"
            result = await run_in_threadpool(turn_off_unmanaged, report_path)
        with _torque_guard:
            _torque_state = "idle"
            _torque_process = None
            _torque_report_path = None
            _torque_fault = None
        _torque_verified_off = True
        with _conversation_motion_guard:
            if _conversation_motion_process is not None and _conversation_motion_process.poll() is not None:
                _conversation_motion_process = None
                _conversation_motion_report = None
                _conversation_motion_id = None
                _conversation_motion_return_requested = False
        with _reset_guard:
            if _reset_fault and "Motor health: torque=" in _reset_fault:
                _reset_fault = None
        return result
    except BaseException as exc:
        with _torque_guard:
            _torque_state = "holding" if process is not None and process.poll() is None else "idle"
            _torque_fault = str(exc)
        _torque_verified_off = False
        if isinstance(exc, (RuntimeError, TimeoutError, OSError, subprocess.TimeoutExpired)):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise


@app.get("/")
def index() -> FileResponse:
    if not (UI_DIST / "index.html").is_file():
        raise HTTPException(status_code=503, detail="UI noch nicht gebaut. Siehe ui/README.md.")
    return FileResponse(UI_DIST / "index.html")


if UI_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("This local-only server may bind only to loopback")
    bind_host = "127.0.0.1" if args.host == "localhost" else args.host
    family = socket.AF_INET6 if bind_host == "::1" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((bind_host, args.port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                parser.error(f"Local backend already uses {bind_host}:{args.port}; "
                             "use the existing server or stop it before starting another.")
            raise
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
