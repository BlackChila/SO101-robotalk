"""API checks for browser PTT upload and the robot-motion boundary."""

import asyncio
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_web  # noqa: E402


def make_webm() -> bytes:
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
            "-c:a", "libopus", "-f", "webm", "pipe:1",
        ],
        check=True, capture_output=True,
    )
    return result.stdout


class AsrWebTests(unittest.TestCase):
    def test_asgi_startup_warms_asr(self) -> None:
        with (
            patch.object(asr_web, "recover_torque_reset_fault") as recover,
            patch.object(asr_web, "start_asr_warmup") as warm,
        ):
            async def startup() -> None:
                async with asr_web.lifespan(asr_web.app):
                    pass

            asyncio.run(startup())
        self.assertIs(asr_web.app.router.lifespan_context, asr_web.lifespan)
        recover.assert_called_once_with()
        warm.assert_called_once_with()

    def test_missing_follower_starts_voice_only_without_motion_process(self) -> None:
        call = SimpleNamespace(headers={"x-so101-conversation": "operator-call"})
        with patch.object(asr_web, "follower_port_available", return_value=False), \
             patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "torque_state", return_value=("idle", None)), \
             patch.object(asr_web, "_conversation_motion_process", None), \
             patch.object(asr_web, "subprocess") as subprocess_mock:
            self.assertEqual(asyncio.run(asr_web.conversation_motion_start(call)),
                             {"status": "voice-only", "sessionId": None})
            subprocess_mock.Popen.assert_not_called()
        with patch.object(asr_web, "follower_port_available", return_value=False), \
             patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "torque_state", return_value=("idle", None)), \
             patch.object(asr_web, "_conversation_motion_process",
                          SimpleNamespace(poll=lambda: None)):
            with self.assertRaises(HTTPException) as active:
                asyncio.run(asr_web.conversation_motion_start(call))
            self.assertEqual(active.exception.status_code, 409)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(asr_web, "follower_port_available", return_value=True), \
             patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "torque_state", return_value=("idle", None)), \
             patch.object(asr_web, "_conversation_motion_process", None), \
             patch.object(asr_web, "INTRO_TAKE", Path(directory) / "missing-intro"), \
             patch.object(asr_web, "subprocess") as subprocess_mock:
            with self.assertRaises(HTTPException) as missing_intro:
                asyncio.run(asr_web.conversation_motion_start(call))
            self.assertEqual(missing_intro.exception.status_code, 503)
            subprocess_mock.Popen.assert_not_called()

    def test_follower_port_preflight_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "pose.json"
            config.write_text(json.dumps({"port": "/dev/null"}))
            with patch.object(asr_web, "POSE_CONFIG", config):
                self.assertTrue(asr_web.follower_port_available())
                config.write_text(json.dumps({"port": str(Path(directory) / "missing-serial")}))
                self.assertFalse(asr_web.follower_port_available())

    def test_conversation_motion_requires_call_and_respects_follower_owner(self) -> None:
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(asr_web.conversation_motion_start(SimpleNamespace(headers={})))
        self.assertEqual(denied.exception.status_code, 403)
        with patch.object(asr_web, "reset_state", return_value=("holding", None)), \
             patch.object(asr_web, "torque_state", return_value=("idle", None)):
            with self.assertRaises(HTTPException) as busy:
                asyncio.run(asr_web.conversation_motion_start(SimpleNamespace(
                    headers={"x-so101-conversation": "operator-call"})))
        self.assertEqual(busy.exception.status_code, 409)

    def test_stopped_conversation_can_be_offered_a_verified_return(self) -> None:
        session_id = "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory) / "outputs"
            outputs.mkdir()
            (outputs / f"conversation-motion-{session_id}.json").write_text(json.dumps({
                "state": "stopped", "follower_torque_holding": True,
                "task_was_started": True, "ended_at_unix": asr_web.time.time(),
            }))
            with patch.object(asr_web, "ROOT", Path(directory)), \
                 patch.object(asr_web, "conversation_motion_status", return_value={
                     "state": "idle", "sessionId": None, "active": False, "occupied": False}):
                status = asr_web.conversation_motion_get_status(session_id)
                self.assertTrue(status["returnAvailable"])
                self.assertEqual(status["sessionId"], session_id)

    def test_occupied_stopped_conversation_exposes_return_availability(self) -> None:
        session_id = "b" * 32
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "outputs" / f"conversation-motion-{session_id}.json"
            report_path.parent.mkdir()
            report_path.write_text(json.dumps({
                "state": "stopped", "follower_torque_holding": True,
                "task_was_started": True, "ended_at_unix": asr_web.time.time(),
            }))
            with patch.object(asr_web, "ROOT", Path(directory)), \
                 patch.object(asr_web, "_conversation_motion_process",
                              SimpleNamespace(poll=lambda: 0)), \
                 patch.object(asr_web, "_conversation_motion_report", report_path), \
                 patch.object(asr_web, "_conversation_motion_id", session_id):
                self.assertTrue(asr_web.conversation_motion_get_status()["returnAvailable"])
                (report_path.parent / f"conversation-return-{session_id}.json").write_text(
                    json.dumps({"returned_to_start": True}))
                self.assertFalse(asr_web.conversation_motion_get_status()["returnAvailable"])

    def test_recovered_return_requires_explicit_end_action(self) -> None:
        request = asr_web.ConversationMotionSession(sessionId="a" * 32)
        with patch.object(asr_web.subprocess, "Popen") as start:
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.conversation_motion_return_stopped(
                    request, SimpleNamespace(headers={})))
        self.assertEqual(denied.exception.status_code, 403)
        start.assert_not_called()

    def test_conversation_gripper_level_requires_finished_intro(self) -> None:
        with patch.object(asr_web, "conversation_motion_status", return_value={"state": "intro"}), \
             patch.object(asr_web, "send_conversation_motion") as send:
            with self.assertRaises(HTTPException) as early:
                asr_web.conversation_motion_level(asr_web.ConversationMotionLevel(
                    sessionId="a" * 32, level=0.5))
        self.assertEqual(early.exception.status_code, 409)
        send.assert_not_called()

    def test_conversation_level_is_timestamped_and_task_motion_takes_priority(self) -> None:
        request = asr_web.ConversationMotionLevel(sessionId="a" * 32, level=0.7)
        with patch.object(asr_web, "conversation_motion_status", return_value={"state": "holding"}), \
             patch.object(asr_web.time, "monotonic", return_value=123.0), \
             patch.object(asr_web, "send_conversation_motion") as send:
            self.assertEqual(asr_web.conversation_motion_level(request), {"status": "ok"})
            send.assert_called_once_with("a" * 32, {"op": "speech_level", "level": 0.7, "sent_at": 123.0})
        for state in ({"state": "task"}, {"state": "holding", "speechGripperAvailable": False}):
            with patch.object(asr_web, "conversation_motion_status", return_value=state), \
                 patch.object(asr_web, "send_conversation_motion") as send:
                self.assertEqual(asr_web.conversation_motion_level(request), {"status": "ignored"})
                send.assert_not_called()

    def test_conversation_return_accepts_positioning_intro_and_holding(self) -> None:
        request = asr_web.ConversationMotionSession(sessionId="a" * 32)
        for state in ("starting", "positioning", "intro", "holding"):
            with self.subTest(state=state), \
                 patch.object(asr_web, "conversation_motion_status", return_value={"state": state}), \
                 patch.object(asr_web, "_active_task", None), \
                 patch.object(asr_web, "send_conversation_motion") as send:
                self.assertEqual(asr_web.conversation_motion_return(request), {"status": "returning"})
                send.assert_called_once_with("a" * 32, {"op": "return_to_start"}, mark_return=True)
        for state in ("failed", "stopped", "task"):
            with self.subTest(state=state), \
                 patch.object(asr_web, "conversation_motion_status", return_value={"state": state}), \
                 patch.object(asr_web, "send_conversation_motion") as send:
                with self.assertRaises(HTTPException):
                    asr_web.conversation_motion_return(request)
                send.assert_not_called()

    def test_conversation_return_after_task_requires_task_to_be_stopped(self) -> None:
        request = asr_web.ConversationMotionSession(sessionId="a" * 32)
        with patch.object(asr_web, "conversation_motion_status", return_value={
                    "state": "holding", "taskWasStarted": True}), \
             patch.object(asr_web, "_active_task", None), \
             patch.object(asr_web, "send_conversation_motion") as send:
            self.assertEqual(asr_web.conversation_motion_return(request), {"status": "returning"})
            send.assert_called_once_with("a" * 32, {"op": "return_to_start"}, mark_return=True)
        with patch.object(asr_web, "_active_task", {"conversationSessionId": "a" * 32}), \
             patch.object(asr_web, "send_conversation_motion") as send:
            with self.assertRaises(HTTPException) as active:
                asr_web.conversation_motion_return(request)
            self.assertEqual(active.exception.status_code, 409)
            send.assert_not_called()

    def test_conversation_stop_holds_torque_and_uses_graceful_stop_after_intro(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "motion.json"
            report.write_text(json.dumps({"state": "holding", "follower_torque_holding": True}))
            process = SimpleNamespace(poll=lambda: None, wait=lambda timeout: 0,
                                      stdin=SimpleNamespace(fileno=lambda: 9))
            with patch.object(asr_web, "_conversation_motion_process", process), \
                 patch.object(asr_web, "_conversation_motion_report", report), \
                 patch.object(asr_web, "_conversation_motion_id", "a" * 32), \
                 patch.object(asr_web, "_conversation_motion_return_requested", False), \
                 patch.object(asr_web.os, "write", return_value=14) as write:
                self.assertEqual(asr_web.stop_conversation_motion("a" * 32),
                                 {"status": "stopped", "followerTorqueHolding": True,
                                  "returnedToStart": False})
                write.assert_called_once_with(9, b'{"op":"stop"}\n')
                self.assertIsNone(asr_web._conversation_motion_process)

    def test_failed_hold_releases_exited_controller_but_keeps_fault_visible(self) -> None:
        session_id = "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "motion.json"
            report.write_text(json.dumps({"state": "failed", "follower_torque_holding": False,
                                          "cleanup_error": "Follower hold unverified: gripper 45 C"}))
            process = SimpleNamespace(poll=lambda: 1, wait=Mock(return_value=1))
            with patch.object(asr_web, "_conversation_motion_process", process), \
                 patch.object(asr_web, "_conversation_motion_report", report), \
                 patch.object(asr_web, "_conversation_motion_id", session_id):
                with self.assertRaisesRegex(RuntimeError, "gripper 45 C"):
                    asr_web.stop_conversation_motion(session_id)
                self.assertIsNone(asr_web._conversation_motion_process)
                status = asr_web.conversation_motion_get_status(session_id)
                self.assertEqual(status["state"], "failed")
                self.assertFalse(status["occupied"])
                self.assertIn("gripper 45 C", status["error"])

    def test_status_retires_exited_failed_controller_after_page_reload(self) -> None:
        session_id = "b" * 32
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "motion.json"
            report.write_text(json.dumps({"state": "failed", "follower_torque_holding": False,
                                          "error": "previous gripper fault"}))
            process = SimpleNamespace(poll=lambda: 1)
            with patch.object(asr_web, "_conversation_motion_process", process), \
                 patch.object(asr_web, "_conversation_motion_report", report), \
                 patch.object(asr_web, "_conversation_motion_id", session_id):
                status = asr_web.conversation_motion_status()
                self.assertIsNone(asr_web._conversation_motion_process)
                self.assertFalse(status["occupied"])
                self.assertEqual(status["error"], "previous gripper fault")

    def test_normal_conversation_end_requests_return_and_waits_for_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "motion.json"
            report.write_text(json.dumps({"state": "holding", "returned_to_start": True,
                                          "task_was_started": True, "follower_torque_holding": True}))
            process = SimpleNamespace(poll=lambda: None, wait=Mock(return_value=0),
                                      stdin=SimpleNamespace(fileno=lambda: 9))
            with patch.object(asr_web, "_conversation_motion_process", process), \
                 patch.object(asr_web, "_conversation_motion_report", report), \
                 patch.object(asr_web, "_conversation_motion_id", "a" * 32), \
                 patch.object(asr_web, "_conversation_motion_return_requested", False), \
                 patch.object(asr_web.os, "write", side_effect=lambda fd, data: len(data)) as write:
                self.assertEqual(asr_web.stop_conversation_motion("a" * 32, True),
                                 {"status": "stopped", "followerTorqueHolding": True,
                                  "returnedToStart": True})
                write.assert_called_once_with(9, b'{"op":"return_to_start"}\n')
                process.wait.assert_called_once_with(timeout=90)

    def test_return_cancel_interrupts_even_before_worker_reports_returning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "motion.json"
            report.write_text(json.dumps({"state": "holding", "follower_torque_holding": True}))
            process = SimpleNamespace(poll=lambda: None, wait=Mock(return_value=0),
                                      terminate=Mock(), stdin=SimpleNamespace(fileno=lambda: 9))
            with patch.object(asr_web, "_conversation_motion_process", process), \
                 patch.object(asr_web, "_conversation_motion_report", report), \
                 patch.object(asr_web, "_conversation_motion_id", "a" * 32), \
                 patch.object(asr_web, "_conversation_motion_return_requested", True), \
                 patch.object(asr_web.os, "write") as write:
                result = asr_web.stop_conversation_motion("a" * 32)
                self.assertFalse(result["returnedToStart"])
                process.terminate.assert_called_once_with()
                write.assert_not_called()

    def test_completed_return_requires_recorded_start_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "motion.json"
            report.write_text(json.dumps({"state": "stopped", "follower_torque_holding": True}))
            process = SimpleNamespace(poll=lambda: 0, wait=Mock(return_value=0))
            with patch.object(asr_web, "_conversation_motion_process", process), \
                 patch.object(asr_web, "_conversation_motion_report", report), \
                 patch.object(asr_web, "_conversation_motion_id", "a" * 32):
                with self.assertRaisesRegex(RuntimeError, "initial pose"):
                    asr_web.stop_conversation_motion("a" * 32, True)

    def test_conversation_speech_is_separate_from_robot_task(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "python"
            python.touch()
            manifest = root / "manifest.json"
            manifest.touch()

            def synthesize(payload):
                with wave.open(payload["path"], "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(16000)
                    output.writeframes(b"\x00\x00" * 160)
                return {"sampleRate": 16000, "seconds": 0.01}

            with patch.object(asr_web, "TTS_PYTHON", python), \
                 patch.object(asr_web, "TTS_MODEL", root), \
                 patch.object(asr_web, "TTS_MANIFEST", manifest), \
                 patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
                 patch.object(asr_web.tts_worker, "request", side_effect=synthesize), \
                 patch.object(asr_web, "execute_model_task") as robot_task:
                self.assertTrue(asr_web.conversation_status()["ttsReady"])
                response = asyncio.run(asr_web.conversation_speak(asr_web.SpeakRequest(
                    text="Hallo William", speaker="Ryan")))
                self.assertEqual(response.media_type, "audio/wav")
                self.assertTrue(response.body.startswith(b"RIFF"))
                with self.assertRaises(ValueError):
                    asr_web.SpeakRequest(text="Hallo", speaker="invalid")
                robot_task.assert_not_called()

    def test_conversation_prepare_warms_speech_without_robot_commands(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            files = [Path(directory) / name for name in
                     ("python", "manifest", "intro", "motion", "flux-python")]
            for path in files:
                path.touch()
            with patch.object(asr_web, "TTS_PYTHON", files[0]), \
                 patch.object(asr_web, "TTS_MANIFEST", files[1]), \
                 patch.object(asr_web, "INTRO_TAKE", files[2]), \
                 patch.object(asr_web, "CONVERSATION_MOTION_RUNNER", files[3]), \
                 patch.object(asr_web, "FLUX_PYTHON", files[4]), \
                 patch.object(asr_web, "policy_session", SimpleNamespace(model_id=None)), \
                 patch.object(asr_web, "camera_session", SimpleNamespace(model_id=None)), \
                 patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
                 patch.object(asr_web.conversation_llm, "ensure_model_loaded",
                              return_value={"ready": True}) as dialogue, \
                 patch.object(asr_web.tts_worker, "ensure_ready") as tts, \
                 patch.object(asr_web, "holder_command") as holder:
                self.assertEqual(asyncio.run(asr_web.conversation_prepare()),
                                 {"dialogueReady": True, "ttsReady": True, "introReady": True})
                dialogue.assert_called_once()
                tts.assert_called_once()
                holder.assert_not_called()

    def test_voice_only_preparation_does_not_require_intro_controller(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python, manifest = root / "python", root / "manifest"
            python.touch()
            manifest.touch()
            with patch.object(asr_web, "TTS_PYTHON", python), \
                 patch.object(asr_web, "TTS_MANIFEST", manifest), \
                 patch.object(asr_web, "INTRO_TAKE", root / "missing-intro"), \
                 patch.object(asr_web, "follower_port_available", return_value=False), \
                 patch.object(asr_web, "policy_session", SimpleNamespace(model_id=None)), \
                 patch.object(asr_web, "camera_session", SimpleNamespace(model_id=None)), \
                 patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
                 patch.object(asr_web.conversation_llm, "ensure_model_loaded",
                              return_value={"ready": True}), \
                 patch.object(asr_web.tts_worker, "ensure_ready") as warm:
                result = asyncio.run(asr_web.conversation_prepare())
                self.assertTrue(result["dialogueReady"])
                warm.assert_called_once()

    def test_piper_conversation_routes_speech_without_robot_commands(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python, model, config, intro, motion, flux = [root / name for name in
                ("python", "voice.onnx", "voice.onnx.json", "intro", "motion", "flux")]
            for path in (python, model, config, intro, motion, flux):
                path.touch()

            def synthesize(payload):
                if payload.get("op") == "prepare":
                    return {"ready": True}
                with wave.open(payload["path"], "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(22050)
                    output.writeframes(b"\x00\x00" * 220)
                return {"sampleRate": 22050, "seconds": 0.01}

            with patch.object(asr_web, "PIPER_PYTHON", python), \
                 patch.object(asr_web, "PIPER_MODEL", model), \
                 patch.object(asr_web, "PIPER_KERSTIN_MODEL", model), \
                 patch.object(asr_web, "PIPER_AMY_MODEL", model), \
                 patch.object(asr_web, "INTRO_TAKE", intro), \
                 patch.object(asr_web, "CONVERSATION_MOTION_RUNNER", motion), \
                 patch.object(asr_web, "FLUX_PYTHON", flux), \
                 patch.object(asr_web, "policy_session", SimpleNamespace(model_id=None)), \
                 patch.object(asr_web, "camera_session", SimpleNamespace(model_id=None)), \
                 patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
                 patch.object(asr_web.conversation_llm, "ensure_model_loaded",
                              return_value={"ready": True}), \
                 patch.object(asr_web.conversation_llm, "model_status",
                              return_value={"ready": True, "model": "qwen"}), \
                 patch.object(asr_web.piper_worker, "ensure_ready") as warm, \
                 patch.object(asr_web.piper_worker, "request", side_effect=synthesize) as speak, \
                 patch.object(asr_web, "execute_model_task") as robot_task:
                self.assertTrue(asr_web.conversation_status("piper")["piperReady"])
                self.assertTrue(asr_web.conversation_status("piper", "Kerstin")["piperReady"])
                self.assertTrue(asr_web.conversation_status("piper", "Amy")["piperReady"])
                self.assertFalse(asr_web.conversation_status("piper", "unknown")["piperReady"])
                result = asyncio.run(asr_web.conversation_prepare(
                    asr_web.PrepareConversationRequest(mode="piper", voice="Kerstin")))
                self.assertTrue(result["ttsReady"])
                response = asyncio.run(asr_web.conversation_speak(asr_web.SpeakRequest(
                    text="Hallo William", engine="piper", voice="Kerstin")))
                self.assertTrue(response.body.startswith(b"RIFF"))
                warm.assert_called_once()
                self.assertEqual(speak.call_count, 2)
                self.assertEqual(speak.call_args_list[0].args[0],
                                 {"op": "prepare", "voice": "Kerstin"})
                self.assertEqual(speak.call_args_list[1].args[0]["voice"], "Kerstin")
                english = asyncio.run(asr_web.conversation_speak(asr_web.SpeakRequest(
                    text="Hello William", engine="piper", voice="Amy")))
                self.assertTrue(english.body.startswith(b"RIFF"))
                self.assertEqual(speak.call_args_list[2].args[0]["voice"], "Amy")
                robot_task.assert_not_called()

    def test_conversation_reply_uses_lm_studio_without_robot_task(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch.object(asr_web.conversation_llm, "model_status", return_value={
                 "ready": True, "model": "qwen/qwen3.8-27b"}), \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
             patch.object(asr_web.conversation_llm, "reply", return_value={
                 "reply": "Hallo!", "responseId": "resp_new"}) as worker, \
             patch.object(asr_web, "execute_model_task") as robot_task:
            request = asr_web.ConversationRequest(text="Hallo", previousResponseId="resp_old")
            response = asyncio.run(asr_web.conversation_reply(request))
            self.assertEqual(response, {"reply": "Hallo!", "responseId": "resp_new"})
            worker.assert_called_once_with("Hallo", "resp_old")
            robot_task.assert_not_called()

    def test_physical_task_requires_ptt_and_new_holder(self) -> None:
        request = asr_web.ModelRequest(prompt="Greif den Ball", liveCamera=True)
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(asr_web.execute_model_task("molmoact2", request, SimpleNamespace(headers={})))
        self.assertEqual(denied.exception.status_code, 403)
        with patch.object(asr_web, "physical_holder_ready", return_value=False):
            with self.assertRaises(HTTPException) as not_ready:
                asyncio.run(asr_web.execute_model_task("molmoact2", request, SimpleNamespace(
                    headers={"x-so101-execute": "operator-ptt"})))
        self.assertEqual(not_ready.exception.status_code, 409)

    def test_ptt_replans_until_stopped_for_each_selected_model(self) -> None:
        pose = dict.fromkeys(("shoulder_pan", "shoulder_lift", "elbow_flex",
                              "wrist_flex", "wrist_roll", "gripper"), 0.0)
        for model in ("molmoact2",):
            calls = []

            def holder(command, **_):
                calls.append(command["op"])
                if command["op"] in {"task_active", "task_inactive"}:
                    return {"status": command["op"]}
                if command["op"] == "snapshot":
                    Path(command["observation_path"]).touch()
                    return {"status": "observed", "model": model,
                            "observation_path": command["observation_path"], "state": pose}
                if calls.count("execute") == 2:
                    asr_web._active_task["stop"].set()
                return {"status": "executed", "executedActions": 2, "measured_after": pose}

            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(asr_web, "ROOT", Path(directory)), \
                 patch.object(asr_web, "_active_task", None), \
                 patch.object(asr_web, "physical_holder_ready", return_value=True), \
                 patch.object(asr_web, "policy_session", SimpleNamespace(ready_model_id=model)), \
                 patch.object(asr_web, "camera_session", SimpleNamespace(model_id=model)), \
                 patch.object(asr_web, "holder_command", side_effect=holder), \
                 patch.object(asr_web, "predict_physical_chunk", return_value={
                     "actionCount": 2, "actions": [pose, pose]}) as predict:
                (Path(directory) / "outputs").mkdir()
                result = asyncio.run(asr_web.execute_model_task(model, asr_web.ModelRequest(
                    prompt="Greif den Ball", liveCamera=True), SimpleNamespace(
                    headers={"x-so101-execute": "operator-ptt"})))
                import time
                deadline = time.monotonic() + 2
                while asr_web.task_status()["state"] == "running" and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(asr_web.task_status()["state"], "stopped")
                self.assertEqual(asr_web.task_status()["chunks"], 2)
                self.assertEqual(asr_web.task_status()["actions"], 4)
                self.assertEqual(calls, ["task_active", "snapshot", "execute",
                                         "snapshot", "execute", "task_inactive"])
                self.assertEqual(result["status"], "started")
                self.assertEqual(predict.call_count, 2)

    def test_new_prompt_invalidates_old_block_and_stop_sets_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "outputs"
            output.mkdir()
            run = {"id": "test", "model": "molmoact2", "prompt": "alt", "state": "running",
                   "chunks": 0, "actions": 0, "startedAt": 1.0, "endedAt": None,
                   "message": "läuft", "generation": 0, "stop": threading.Event(),
                   "epochPath": output / "ui-robot-epoch-test.txt"}
            run["epochPath"].write_text("0")
            with patch.object(asr_web, "_active_task", run), \
                 patch.object(asr_web, "physical_holder_ready", return_value=True):
                updated = asyncio.run(asr_web.execute_model_task("molmoact2",
                    asr_web.ModelRequest(prompt="neu", liveCamera=True),
                    SimpleNamespace(headers={"x-so101-execute": "operator-ptt"})))
                self.assertEqual(updated["status"], "updated")
                self.assertEqual(run["generation"], 1)
                self.assertEqual(run["epochPath"].read_text(), "1")
                stopped = asyncio.run(asr_web.stop_physical_task(SimpleNamespace(
                    headers={"x-so101-stop": "operator-click"})))
                self.assertEqual(stopped["status"], "stopping")
                self.assertTrue(run["stop"].is_set())
                self.assertEqual(run["epochPath"].read_text(), "2")

    def test_replacement_prompt_reaches_next_physical_prediction(self) -> None:
        first_predicting = threading.Event()
        release_first = threading.Event()
        predictions = []
        executions = []
        pose = dict.fromkeys(("shoulder_pan", "shoulder_lift", "elbow_flex",
                              "wrist_flex", "wrist_roll", "gripper"), 0.0)

        def holder(command, **_):
            if command["op"] == "snapshot":
                Path(command["observation_path"]).touch()
                return {"status": "observed", "model": "molmoact2",
                        "observation_path": command["observation_path"], "state": pose}
            if command["op"] == "execute":
                executions.append(command["epoch"])
                asr_web._active_task["stop"].set()
                return {"status": "executed", "executedActions": 1}
            return {"status": command["op"]}

        def predict(_model, prompt, **_):
            predictions.append(prompt)
            if prompt == "first":
                first_predicting.set()
                self.assertTrue(release_first.wait(2))
            return {"actions": [pose]}

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(asr_web, "ROOT", Path(directory)), \
             patch.object(asr_web, "_active_task", None), \
             patch.object(asr_web, "physical_holder_ready", return_value=True), \
             patch.object(asr_web, "policy_session", SimpleNamespace(ready_model_id="molmoact2")), \
             patch.object(asr_web, "camera_session", SimpleNamespace(model_id="molmoact2")), \
             patch.object(asr_web, "holder_command", side_effect=holder), \
             patch.object(asr_web, "predict_physical_chunk", side_effect=predict):
            (Path(directory) / "outputs").mkdir()
            browser = SimpleNamespace(headers={"x-so101-execute": "operator-ptt"})
            try:
                started = asyncio.run(asr_web.execute_model_task("molmoact2",
                    asr_web.ModelRequest(prompt="first", liveCamera=True), browser))
                self.assertEqual(started["status"], "started")
                self.assertTrue(first_predicting.wait(2))
                updated = asyncio.run(asr_web.execute_model_task("molmoact2",
                    asr_web.ModelRequest(prompt="second", liveCamera=True), browser))
                self.assertEqual(updated["status"], "updated")
            finally:
                release_first.set()
            deadline = time.monotonic() + 2
            while asr_web.task_status()["state"] == "running" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(asr_web.task_status()["state"], "stopped")
            self.assertEqual(predictions, ["first", "second"])
            self.assertEqual(executions, [1])
            self.assertEqual(asr_web.task_status()["prompt"], "second")
            self.assertEqual(asr_web.task_status()["generation"], 1)
            self.assertEqual(asr_web.task_status()["inferenceGeneration"], 1)
            self.assertEqual(asr_web.task_status()["executedGeneration"], 1)

    @patch.object(asr_web, "FLUX_PYTHON", Path(sys.executable))
    def test_torque_toggle_starts_hold_then_releases_it(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        holder = SimpleNamespace(poll=lambda: None)
        request = SimpleNamespace(headers={"x-so101-torque": "operator-click"})
        with (
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web, "static_reset_blocker", return_value=None),
            patch.object(asr_web, "_reset_state", "idle"),
            patch.object(asr_web, "_reset_process", None),
            patch.object(asr_web, "_torque_state", "idle"),
            patch.object(asr_web, "_torque_process", None),
            patch.object(asr_web, "_torque_report_path", None),
            patch.object(asr_web, "_torque_fault", None),
            patch.object(asr_web, "_torque_verified_off", True),
            patch.object(asr_web, "start_torque_process", return_value=holder) as start,
            patch.object(asr_web, "release_torque_process", return_value={"status": "off"}) as release,
        ):
            self.assertEqual(asr_web.status()["torqueAction"], "on")
            self.assertEqual(asyncio.run(asr_web.torque_on(request))["status"], "holding")
            self.assertEqual(asr_web.status()["torqueAction"], "off")
            self.assertEqual(asyncio.run(asr_web.torque_off(request))["status"], "off")
            self.assertEqual(asr_web.status()["torqueAction"], "on")
            self.assertTrue(asr_web._torque_verified_off)
            start.assert_called_once()
            release.assert_called_once()

    @patch.object(asr_web, "FLUX_PYTHON", Path(sys.executable))
    def test_torque_off_handles_unknown_state_and_clears_torque_fault(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        request = SimpleNamespace(headers={"x-so101-torque": "operator-click"})
        with (
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web, "_reset_state", "idle"),
            patch.object(asr_web, "_reset_process", None),
            patch.object(asr_web, "_reset_fault", "Motor health: torque={'motor': 1}"),
            patch.object(asr_web, "_torque_state", "idle"),
            patch.object(asr_web, "_torque_process", None),
            patch.object(asr_web, "_torque_report_path", None),
            patch.object(asr_web, "_torque_verified_off", False),
            patch.object(asr_web, "turn_off_unmanaged", return_value={"status": "off"}) as off,
        ):
            self.assertEqual(asr_web.status()["torqueAction"], "off")
            self.assertEqual(asyncio.run(asr_web.torque_off(request))["status"], "off")
            self.assertIsNone(asr_web._reset_fault)
            self.assertTrue(asr_web._torque_verified_off)
            off.assert_called_once()

    def test_torque_change_requires_explicit_click(self) -> None:
        for endpoint in (asr_web.torque_on, asr_web.torque_off):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(endpoint(SimpleNamespace(headers={})))
            self.assertEqual(raised.exception.status_code, 403)

    def test_start_position_keeps_selected_model_ready_for_later_prompt(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with (
            patch.object(asr_web, "reset_blocker", return_value=None),
            patch.object(asr_web, "static_reset_blocker", return_value=None),
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web, "_reset_state", "idle"),
            patch.object(asr_web, "_reset_process", None),
            patch.object(asr_web, "_reset_report_path", None),
            patch.object(asr_web, "start_reset_process", return_value=object()),
            patch.object(asr_web.policy_session, "stop") as stop,
        ):
            result = asyncio.run(asr_web.reset(SimpleNamespace(
                headers={"x-so101-reset": "operator-click"})))
            self.assertEqual(asr_web._reset_state, "holding")
        self.assertEqual(result["status"], "holding")
        stop.assert_not_called()

    def test_return_to_start_uses_held_controller_without_unloading_model(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        request = SimpleNamespace(headers={"x-so101-reset": "operator-click"})
        with (
            patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False}),
            patch.object(asr_web, "holder_supports_return", return_value=True),
            patch.object(asr_web, "static_reset_blocker", return_value=None),
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web, "_return_running", False),
            patch.object(asr_web, "holder_command", return_value={
                "status": "returned", "measured_after": {"elbow_flex": 0.0}}) as holder,
            patch.object(asr_web.policy_session, "stop") as stop_policy,
        ):
            result = asyncio.run(asr_web.return_to_start(request))
            self.assertEqual(result["status"], "returned")
            holder.assert_called_once_with({"op": "return_to_start"}, timeout_s=150)
            stop_policy.assert_not_called()
            asr_web._policy_lock.acquire()
            try:
                with self.assertRaises(HTTPException) as busy:
                    asyncio.run(asr_web.return_to_start(request))
            finally:
                asr_web._policy_lock.release()
            self.assertEqual(busy.exception.status_code, 409)
            holder.assert_called_once()

    def test_return_to_start_stops_active_model_before_moving(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        events = []
        request = SimpleNamespace(headers={"x-so101-reset": "operator-click"})
        def wait_for_stop():
            events.append("held")
            asr_web._policy_lock.acquire()

        def move(*_args, **_kwargs):
            events.append("return")
            return {"status": "returned", "measured_after": {"elbow_flex": 0.0}}

        with (
            patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False}),
            patch.object(asr_web, "holder_supports_return", return_value=True),
            patch.object(asr_web, "static_reset_blocker", return_value=None),
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web, "_return_running", False),
            patch.object(asr_web, "request_physical_task_stop", side_effect=lambda: (
                events.append("stop") or {"state": "stopping"})),
            patch.object(asr_web, "wait_for_stopped_task", side_effect=wait_for_stop),
            patch.object(asr_web, "holder_command", side_effect=move),
        ):
            result = asyncio.run(asr_web.return_to_start(request))
        self.assertEqual(result["status"], "returned")
        self.assertEqual(events, ["stop", "held", "return"])
        self.assertFalse(asr_web._policy_lock.locked())

    def test_return_is_available_during_active_model_task(self) -> None:
        with (
            patch.object(asr_web, "reset_state", return_value=("holding", None)),
            patch.object(asr_web, "torque_state", return_value=("idle", None)),
            patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False, "active": False}),
            patch.object(asr_web, "reset_blocker", return_value="holder active"),
            patch.object(asr_web, "static_reset_blocker", return_value=None),
            patch.object(asr_web, "holder_supports_return", return_value=True),
            patch.object(asr_web, "physical_holder_ready", return_value=True),
            patch.object(asr_web, "task_status", return_value={"model": "molmoact2", "state": "running"}),
        ):
            result = asr_web.status()
        self.assertTrue(result["returnAvailable"])
        self.assertIn("stopped", result["returnMessage"])

    def test_return_reservation_rejects_new_motor_task(self) -> None:
        with (
            patch.object(asr_web, "_return_running", True),
            patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False}),
            patch.object(asr_web, "physical_holder_ready", return_value=True),
        ):
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.execute_model_task("molmoact2", asr_web.ModelRequest(
                    prompt="Greif den Ball", liveCamera=True),
                    SimpleNamespace(headers={"x-so101-execute": "operator-ptt"})))
        self.assertEqual(denied.exception.status_code, 409)

    def test_stop_request_invalidates_actions_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            epoch_path = Path(directory) / "epoch.txt"
            run = {"id": "run", "model": "molmoact2", "prompt": "move", "state": "running",
                   "chunks": 0, "actions": 0, "startedAt": 1.0, "endedAt": None,
                   "message": "running", "generation": 0,
                   "stop": threading.Event(), "epochPath": epoch_path}
            with patch.object(asr_web, "_active_task", run):
                first = asr_web.request_physical_task_stop()
                second = asr_web.request_physical_task_stop()
            self.assertTrue(run["stop"].is_set())
            self.assertEqual(epoch_path.read_text(), "1")
            self.assertEqual(first["state"], "stopping")
            self.assertEqual(second["generation"], 1)

    def test_stalled_prediction_is_interrupted_before_return(self) -> None:
        policy_lock = threading.Lock()
        policy_lock.acquire()
        with (
            patch.object(asr_web, "_policy_lock", policy_lock),
            patch.object(asr_web, "_active_task", {"state": "stopping"}),
            patch.object(asr_web.policy_session, "interrupt_active_request",
                         side_effect=policy_lock.release) as interrupt,
        ):
            asr_web.wait_for_stopped_task(timeout_s=2, interrupt_after_s=0)
            self.assertTrue(policy_lock.locked())
            policy_lock.release()
        interrupt.assert_called_once_with()

    def test_interrupted_prediction_finishes_with_confirmed_holder_stop(self) -> None:
        pose = dict.fromkeys(("shoulder_pan", "shoulder_lift", "elbow_flex",
                              "wrist_flex", "wrist_roll", "gripper"), 0.0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outputs").mkdir()
            run = {"id": "run", "model": "molmoact2", "prompt": "move", "state": "running",
                   "chunks": 0, "actions": 0, "startedAt": 1.0, "endedAt": None,
                   "message": "running", "generation": 0, "inferenceGeneration": -1,
                   "executedGeneration": -1, "stop": threading.Event(),
                   "epochPath": root / "outputs/epoch.txt"}
            run["epochPath"].write_text("0")
            calls = []
            def holder(command, **_kwargs):
                calls.append(command["op"])
                if command["op"] == "snapshot":
                    Path(command["observation_path"]).touch()
                    return {"status": "observed", "model": "molmoact2",
                            "observation_path": command["observation_path"], "state": pose}
                return {"status": command["op"]}
            def predict(*_args, **_kwargs):
                run["stop"].set()
                raise RuntimeError("worker interrupted")
            policy_lock = threading.Lock()
            policy_lock.acquire()
            with (patch.object(asr_web, "ROOT", root),
                  patch.object(asr_web, "_active_task", run),
                  patch.object(asr_web, "_policy_lock", policy_lock),
                  patch.object(asr_web, "holder_command", side_effect=holder),
                  patch.object(asr_web, "predict_physical_chunk", side_effect=predict)):
                asr_web.physical_task_loop(run)
            self.assertEqual(run["state"], "stopped")
            self.assertEqual(calls, ["task_active", "snapshot", "task_inactive"])
            self.assertFalse(policy_lock.locked())

    def test_return_to_start_rejects_holder_without_return_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "holder.json"
            report.write_text(json.dumps({"outcome": "reset_pose_holding_torque"}))
            with (patch.object(asr_web, "physical_holder_ready", return_value=True),
                  patch.object(asr_web, "_reset_report_path", report),
                  patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False}),
                  patch.object(asr_web, "holder_command") as holder):
                self.assertFalse(asr_web.holder_supports_return())
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.return_to_start(SimpleNamespace(
                        headers={"x-so101-reset": "operator-click"})))
                self.assertEqual(denied.exception.status_code, 409)
                holder.assert_not_called()
                report.write_text(json.dumps({"outcome": "reset_pose_holding_torque",
                                              "capabilities": ["return_to_start"]}))
                self.assertTrue(asr_web.holder_supports_return())

    def test_prompt_runs_selected_model_while_start_position_is_held(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with (
            patch.object(asr_web, "reset_state", return_value=("holding", None)),
            patch.object(asr_web, "require_no_physical_client"),
            patch.object(asr_web, "camera_switch_guard", contextlib.nullcontext),
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web.camera_session, "capture", return_value={
                "path": "/tmp/camera.npz", "geometry": "test", "frames": 1,
                "capturedAt": 1.0,
            }) as capture,
            patch.object(asr_web, "run_model_inference", return_value={
                "model": "molmoact2", "hardwareCommands": False, "actionCount": 1,
            }) as infer,
        ):
            result = asyncio.run(asr_web.model_infer("molmoact2", asr_web.ModelRequest(
                prompt="Greif den Ball", liveCamera=True)))
        capture.assert_called_once_with("molmoact2")
        infer.assert_called_once_with("molmoact2", "Greif den Ball", camera_npz="/tmp/camera.npz")
        self.assertFalse(result["hardwareCommands"])
        self.assertEqual(result["cameraCapture"]["model"], "molmoact2")

    def test_prompt_waits_until_start_position_travel_has_finished(self) -> None:
        with (
            patch.object(asr_web, "reset_state", return_value=("starting", None)),
            patch.object(asr_web, "run_model_inference") as infer,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(asr_web.model_infer("molmoact2", asr_web.ModelRequest(
                    prompt="Greif den Ball", liveCamera=True)))
        self.assertEqual(raised.exception.status_code, 409)
        infer.assert_not_called()

    @patch.object(type(asr_web.MODEL_PATH), "is_dir", lambda _: True)
    def test_asr_is_ready_only_after_model_load(self) -> None:
        with (
            patch.object(asr_web.torch.cuda, "is_available", return_value=True),
            patch.object(asr_web, "_model", None),
            patch.object(asr_web, "_asr_loading", False),
            patch.object(asr_web, "_asr_error", None),
        ):
            not_started = TestClient(asr_web.app).get("/api/status").json()
        self.assertEqual(not_started["asrMessage"], "Qwen3-ASR has not been loaded yet.")
        with (
            patch.object(asr_web.torch.cuda, "is_available", return_value=True),
            patch.object(asr_web, "_model", None),
            patch.object(asr_web, "_asr_loading", True),
        ):
            loading = TestClient(asr_web.app).get("/api/status").json()
        self.assertFalse(loading["asrReady"])
        self.assertTrue(loading["asrLoading"])
        with (
            patch.object(asr_web.torch.cuda, "is_available", return_value=True),
            patch.object(asr_web, "_model", object()),
            patch.object(asr_web, "_asr_loading", False),
        ):
            ready = TestClient(asr_web.app).get("/api/status").json()
        self.assertTrue(ready["asrReady"])
        self.assertFalse(ready["asrLoading"])

    @patch.object(type(asr_web.MODEL_PATH), "is_dir", lambda _: True)
    def test_webm_ptt_upload_decodes_and_transcribes_once(self) -> None:
        with (
            patch.object(asr_web.torch.cuda, "is_available", return_value=True),
            patch.object(asr_web, "get_model", return_value=object()),
            patch.object(
                asr_web, "transcribe", return_value={"language": "German", "text": "Hallo"},
            ) as transcribe,
        ):
            client = TestClient(asr_web.app)
            response = client.post(
                "/api/transcribe",
                files={"audio": ("recording.webm", io.BytesIO(make_webm()), "audio/webm")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"language": "German", "text": "Hallo"})
        self.assertEqual(transcribe.call_count, 1)
        self.assertEqual(transcribe.call_args.args[2], "German")

    @patch.object(type(asr_web.MODEL_PATH), "is_dir", lambda _: True)
    def test_conversation_upload_accepts_english_transcription(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        class Audio:
            def __init__(self):
                self.sent = False

            async def read(self, _size):
                if self.sent:
                    return b""
                self.sent = True
                return b"test audio"

            async def close(self):
                pass

        with (
            patch.object(asr_web.torch.cuda, "is_available", return_value=True),
            patch.object(asr_web, "get_model", return_value=object()),
            patch.object(asr_web, "decode_audio"),
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web, "transcribe", return_value={
                "language": "English", "text": "Hello"}) as transcribe,
        ):
            result = asyncio.run(asr_web.transcribe_upload(Audio(), "English"))
        self.assertEqual(result, {"language": "English", "text": "Hello"})
        self.assertEqual(transcribe.call_args.args[2], "English")

    def test_reset_remains_blocked_without_validated_travel(self) -> None:
        # This boundary test must not depend on (or invoke) the installed robot.
        with tempfile.TemporaryDirectory() as directory:
            pose = Path(directory) / "unvalidated.json"
            pose.write_text(json.dumps({"automatic_travel_validated": False}))
            with patch.object(asr_web, "POSE_CONFIG", pose), \
                 patch.object(asr_web, "reset_state", return_value=("idle", None)), \
                 patch.object(asr_web, "torque_state", return_value=("idle", None)), \
                 patch.object(asr_web, "conversation_motion_status", return_value={
                     "occupied": False, "active": False}), \
                 patch.object(asr_web, "start_reset_process") as start:
                client = TestClient(asr_web.app)
                response = client.post("/api/reset", headers={"X-SO101-Reset": "operator-click"})
                self.assertEqual(response.status_code, 409)
                self.assertIn("not been validated", response.json()["detail"])
                with patch.object(asr_web.torch.cuda, "is_available", return_value=True):
                    self.assertFalse(client.get("/api/status").json()["resetAvailable"])
                start.assert_not_called()

    def test_validated_reset_click_invokes_isolated_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calibration = root / "calibration.json"
            calibration.write_text("calibration")
            port = root / "serial"
            port.touch()
            runner = root / "runner.py"
            runner.touch()
            pose = root / "pose.json"
            pose.write_text(json.dumps({
                "automatic_travel_validated": True,
                "calibration_path": str(calibration),
                "calibration_sha256": asr_web.hashlib.sha256(calibration.read_bytes()).hexdigest(),
                "port": str(port),
            }))
            with (
                patch.object(asr_web, "POSE_CONFIG", pose),
                patch.object(asr_web, "FLUX_PYTHON", runner),
                patch.object(asr_web, "RESET_RUNNER", runner),
                patch.object(asr_web, "_reset_state", "idle"),
                patch.object(asr_web, "_reset_process", None),
                patch.object(asr_web, "_reset_report_path", None),
                patch.object(asr_web, "_reset_fault", None),
                patch.object(asr_web, "start_reset_process") as start,
                patch.object(asr_web, "release_reset_process", return_value={
                    "status": "released", "message": "Torque off."}) as release,
            ):
                start.return_value.poll.return_value = None
                client = TestClient(asr_web.app)
                self.assertTrue(client.get("/api/status").json()["resetAvailable"])
                denied = client.post("/api/reset")
                self.assertEqual(denied.status_code, 403)
                response = client.post("/api/reset", headers={"X-SO101-Reset": "operator-click"})
                self.assertTrue(client.get("/api/status").json()["resetHolding"])
                released = client.post("/api/reset/release", headers={"X-SO101-Reset": "operator-click"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "holding")
            self.assertEqual(start.call_count, 1)
            self.assertEqual(released.status_code, 200, released.text)
            self.assertEqual(release.call_count, 1)

    def test_nonlocal_browser_origin_cannot_post_audio(self) -> None:
        client = TestClient(asr_web.app)
        response = client.post(
            "/api/transcribe",
            headers={"Origin": "https://example.org"},
            files={"audio": ("recording.webm", b"fake", "audio/webm")},
        )
        self.assertEqual(response.status_code, 403)

    def test_molmo_prompt_is_explicit_and_never_starts_reset(self) -> None:
        with (
            patch.object(asr_web, "run_model_inference", return_value={
                "model": "molmoact2", "prompt": "Greif den Ball", "hardwareCommands": False,
                "observation": "official_sample_top_side", "actionCount": 30,
                "firstAction": {"shoulder_pan": 0.0},
            }) as infer,
            patch.object(asr_web, "start_reset_process") as start_reset,
        ):
            client = TestClient(asr_web.app)
            result = client.post("/api/models/molmoact2/infer", json={"prompt": "  Greif den Ball  "})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertFalse(result.json()["hardwareCommands"])
            infer.assert_called_once_with("molmoact2", "Greif den Ball")
            start_reset.assert_not_called()

    def test_model_endpoint_rejects_empty_and_unknown_models(self) -> None:
        client = TestClient(asr_web.app)
        self.assertEqual(client.post("/api/models/molmoact2/infer", json={"prompt": "   "}).status_code, 422)
        self.assertEqual(client.post("/api/models/unknown/infer", json={"prompt": "Hallo"}).status_code, 404)
        self.assertEqual(client.post(
            "/api/models/molmoact2/infer", headers={"Origin": "https://example.org"},
            json={"prompt": "Hallo"},
        ).status_code, 403)

    def test_task_route_never_executes_without_explicit_ptt(self) -> None:
        with patch.object(asr_web, "holder_command") as holder:
            for model_id in ("molmoact2",):
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.execute_model_task(model_id,
                        asr_web.ModelRequest(prompt="Befehl", liveCamera=True),
                        SimpleNamespace(headers={})))
                self.assertEqual(denied.exception.status_code, 403)
        holder.assert_not_called()

    def test_session_stop_endpoint_waits_for_unload(self) -> None:
        with patch.object(asr_web.policy_session, "stop") as stop:
            response = TestClient(asr_web.app).delete("/api/session")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "stopped"})
        stop.assert_called_once()

    def test_model_unload_keeps_camera_and_physical_holder_untouched(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with (
            patch.object(asr_web, "reset_state", return_value=("holding", None)),
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web.policy_session, "stop") as stop,
            patch.object(asr_web.camera_session, "stop") as stop_camera,
            patch.object(asr_web, "require_no_physical_client") as camera_guard,
            patch.object(asr_web, "holder_command") as holder,
        ):
            response = asyncio.run(asr_web.unload_current_model())
        self.assertEqual(response, {"status": "unloaded"})
        stop.assert_called_once()
        stop_camera.assert_not_called()
        camera_guard.assert_not_called()
        holder.assert_not_called()

    def test_model_unload_refuses_active_model_run(self) -> None:
        with patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web.policy_session, "stop") as stop:
            asr_web._policy_lock.acquire()
            try:
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.unload_current_model())
            finally:
                asr_web._policy_lock.release()
        self.assertEqual(denied.exception.status_code, 409)
        stop.assert_not_called()

    def test_model_selection_unloads_old_and_preloads_new_without_task(self) -> None:
        events = []

        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with (
            patch.object(asr_web, "available_models", return_value=[
                {"id": "molmoact2", "available": True, "message": "bereit"},
            ]),
            patch.object(asr_web, "require_no_physical_client"),
            patch.object(asr_web, "reset_state", return_value=("idle", None)),
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(type(asr_web.policy_session), "model_id", property(lambda _: "retired-policy")),
            patch.object(asr_web.policy_session, "stop", side_effect=lambda: events.append("stop")),
            patch.object(asr_web.camera_session, "select", side_effect=lambda _: (
                events.append("camera") or {"model": "molmoact2", "previews": {}})),
            patch.object(asr_web.policy_session, "preload", side_effect=lambda _: (
                events.append("preload") or {"model": "molmoact2", "ready": True,
                                             "hardwareCommands": False})),
        ):
            response = asyncio.run(asr_web.select_model("molmoact2"))
        self.assertTrue(response["modelReady"])
        self.assertEqual(events, ["stop", "camera", "preload"])

    def test_insta360_view_api_rejects_runs_other_profiles_and_invalid_settings(self) -> None:
        from pydantic import ValidationError
        request = asr_web.Insta360ViewRequest(yaw=-45, pitch=20, roll=0)
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with (
            patch.object(asr_web, "reset_state", return_value=("idle", None)),
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(asr_web.camera_session, "set_insta360_view", return_value={
                "model": "molmoact2", "insta360View": request.model_dump()}) as update,
        ):
            response = asyncio.run(asr_web.set_insta360_camera_view("molmoact2", request))
            self.assertEqual(response["insta360View"], request.model_dump())
            update.assert_called_once_with("molmoact2", request.model_dump())
            for model in ("removed-flux3", "removed-g05"):
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.set_insta360_camera_view(model, request))
                self.assertEqual(denied.exception.status_code, 404)
            asr_web._policy_lock.acquire()
            try:
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.set_insta360_camera_view("molmoact2", request))
                self.assertEqual(denied.exception.status_code, 409)
            finally:
                asr_web._policy_lock.release()
            update.assert_called_once()
            update.side_effect = asr_web.PhysicalCameraLeaseBusy("Physical run")
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.set_insta360_camera_view("molmoact2", request))
            self.assertEqual(denied.exception.status_code, 409)
            self.assertFalse(asr_web._policy_lock.locked())
        for invalid in [{"yaw": 181, "pitch": 0, "roll": 0},
                        {"yaw": 0, "pitch": 91, "roll": 0},
                        {"yaw": True, "pitch": 0, "roll": 0},
                        {"yaw": 0, "pitch": 0, "roll": 0, "width": 320}]:
            with self.assertRaises(ValidationError):
                asr_web.Insta360ViewRequest(**invalid)

    def test_camera_brightness_api_blocks_busy_runs_and_invalid_roles(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)
        request = asr_web.CameraBrightnessRequest(value=12)
        with patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
             patch.object(asr_web.camera_session, "set_camera_brightness", return_value={"ok": True}) as write:
            self.assertTrue(asyncio.run(asr_web.set_camera_brightness("molmoact2", "cam1", request))["ok"])
            write.assert_called_once_with("molmoact2", "cam1", 12)
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.set_camera_brightness("molmoact2", "scene", request))
            self.assertEqual(denied.exception.status_code, 404)
            asr_web._policy_lock.acquire()
            try:
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.set_camera_brightness("molmoact2", "cam0", request))
                self.assertEqual(denied.exception.status_code, 409)
            finally:
                asr_web._policy_lock.release()
            write.assert_called_once()
            write.side_effect = asr_web.PhysicalCameraLeaseBusy("busy")
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.set_camera_brightness("molmoact2", "cam1", request))
            self.assertEqual(denied.exception.status_code, 409)
            self.assertFalse(asr_web._policy_lock.locked())

    def test_model_camera_selection_opens_each_pair_without_loading_weights(self) -> None:
        from unittest.mock import PropertyMock
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)
        with patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "require_no_physical_client") as guard, \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
             patch.object(asr_web.policy_session, "preload") as preload, \
             patch.object(asr_web.policy_session, "stop") as stop, \
             patch.object(asr_web.policy_session.__class__, "model_id", new_callable=PropertyMock, return_value=None), \
             patch.object(asr_web.camera_session.__class__, "model_id", new_callable=PropertyMock, return_value=None), \
             patch.object(asr_web.camera_session, "select", side_effect=lambda model: {"model": model}) as select:
            for model_id in ("molmoact2",):
                result = asyncio.run(asr_web.select_camera_model(model_id))
                self.assertEqual(result["model"], model_id)
                select.assert_called_with(model_id)
            self.assertEqual(guard.call_count, 1)
            preload.assert_not_called()
            stop.assert_not_called()

    def test_conversation_cameras_start_without_loading_or_unloading_policy(self) -> None:
        from unittest.mock import PropertyMock
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)
        with patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "require_no_physical_client"), \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
             patch.object(asr_web.policy_session, "preload") as preload, \
             patch.object(asr_web.policy_session, "stop") as stop, \
             patch.object(asr_web.policy_session.__class__, "model_id", new_callable=PropertyMock, return_value=None) as model, \
             patch.object(asr_web.camera_session.__class__, "model_id", new_callable=PropertyMock, return_value=None), \
             patch.object(asr_web.camera_session, "select", return_value={"model": "conversation"}) as select:
            self.assertEqual(asyncio.run(asr_web.select_camera_model("conversation"))["model"], "conversation")
            select.assert_called_once_with("conversation")
            preload.assert_not_called()
            stop.assert_not_called()
            model.return_value = "molmoact2"
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.select_camera_model("conversation"))
            self.assertEqual(denied.exception.status_code, 409)
            stop.assert_not_called()
            asr_web._policy_lock.acquire()
            try:
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.select_camera_model("conversation"))
                self.assertEqual(denied.exception.status_code, 409)
            finally:
                asr_web._policy_lock.release()

    def test_molmo_wrist_observer_controls_use_existing_camera_guards(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)
        with patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline):
            for name, request in [("brightness", asr_web.CameraBrightnessRequest(value=-32)),
                                  ("exposure", asr_web.CameraExposureRequest(value=50))]:
                with patch.object(asr_web.camera_session, "set_camera_" + name, return_value={"ok": True}) as write:
                    endpoint = getattr(asr_web, "set_camera_" + name)
                    self.assertTrue(asyncio.run(endpoint("molmoact2", "wrist", request))["ok"])
                    write.assert_called_once_with("molmoact2", "wrist", request.value)
                    asr_web._policy_lock.acquire()
                    try:
                        with self.assertRaises(HTTPException) as denied:
                            asyncio.run(endpoint("molmoact2", "wrist", request))
                        self.assertEqual(denied.exception.status_code, 409)
                        write.assert_called_once()
                    finally:
                        asr_web._policy_lock.release()

    def test_camera_exposure_api_blocks_busy_runs_and_invalid_roles(self) -> None:
        from pydantic import ValidationError
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)
        request = asr_web.CameraExposureRequest(value=12)
        with patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
             patch.object(asr_web.camera_session, "set_camera_exposure", return_value={"ok": True}) as write:
            self.assertTrue(asyncio.run(asr_web.set_camera_exposure("molmoact2", "cam1", request))["ok"])
            write.assert_called_once_with("molmoact2", "cam1", 12)
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.set_camera_exposure("molmoact2", "scene", request))
            self.assertEqual(denied.exception.status_code, 404)
            asr_web._policy_lock.acquire()
            try:
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.set_camera_exposure("molmoact2", "cam0", request))
                self.assertEqual(denied.exception.status_code, 409)
            finally:
                asr_web._policy_lock.release()
            write.assert_called_once()
            write.side_effect = asr_web.PhysicalCameraLeaseBusy("busy")
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.set_camera_exposure("molmoact2", "cam1", request))
            self.assertEqual(denied.exception.status_code, 409)
            self.assertFalse(asr_web._policy_lock.locked())
            write.side_effect = ValueError("out of range")
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.set_camera_exposure("molmoact2", "cam0", request))
            self.assertEqual(denied.exception.status_code, 422)
            self.assertFalse(asr_web._policy_lock.locked())
        for invalid in [True, 1.5, "80"]:
            with self.assertRaises(ValidationError):
                asr_web.CameraExposureRequest(value=invalid)

    def test_camera_reload_keeps_loaded_policy_and_refuses_active_run(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        with (
            patch.object(asr_web, "reset_state", return_value=("idle", None)),
            patch.object(asr_web, "require_no_physical_client") as guard,
            patch.object(asr_web, "run_in_threadpool", side_effect=inline),
            patch.object(type(asr_web.policy_session), "model_id", property(lambda _: "molmoact2")),
            patch.object(asr_web.policy_session, "stop") as stop_policy,
            patch.object(asr_web.camera_session, "restart", return_value={
                "model": "molmoact2", "previews": {"scene": {}, "wrist": {}}}) as restart,
        ):
            response = asyncio.run(asr_web.reload_camera_model("molmoact2"))
            self.assertEqual(response["model"], "molmoact2")
            guard.assert_called_once_with()
            restart.assert_called_once_with("molmoact2")
            stop_policy.assert_not_called()
            asr_web._policy_lock.acquire()
            try:
                with self.assertRaises(HTTPException) as denied:
                    asyncio.run(asr_web.reload_camera_model("molmoact2"))
            finally:
                asr_web._policy_lock.release()
            self.assertEqual(denied.exception.status_code, 409)
            restart.assert_called_once()


if __name__ == "__main__":
    unittest.main()
