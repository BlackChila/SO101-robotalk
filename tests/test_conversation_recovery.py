"""Offline regressions for shared voice-session end/start recovery."""
import asyncio
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_web


class ConversationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "outputs").mkdir()
        self.sid = "a" * 32
        self.motion = self.root / "outputs" / f"conversation-motion-{self.sid}.json"
        self.returned = self.root / "outputs" / f"conversation-return-{self.sid}.json"
        for name in ("take", "runner", "python"):
            (self.root / name).touch()
        for name, value in {
            "ROOT": self.root, "INTRO_TAKE": self.root / "take",
            "CONVERSATION_MOTION_RUNNER": self.root / "runner", "FLUX_PYTHON": self.root / "python",
            "_conversation_motion_process": None, "_conversation_motion_report": self.returned,
            "_conversation_motion_id": self.sid, "_conversation_motion_fault": None,
            "_conversation_motion_return_requested": False, "_active_task": None,
            "_conversation_robot_reset_session": None,
        }.items():
            self.stack.enter_context(patch.object(asr_web, name, value))
        for name in ("reset_state", "torque_state"):
            self.stack.enter_context(patch.object(asr_web, name, return_value=("idle", None)))
        self.stack.enter_context(patch.object(asr_web.teleoperation_session, "status", return_value={"occupied": False}))
        self.stack.enter_context(patch.object(asr_web.face_tracking_session, "disable"))
        self.stack.enter_context(patch.object(asr_web.local_conversations, "close_motion"))
        self.motion.write_text(json.dumps({"state": "stopped", "follower_torque_holding": True,
                                          "ended_at_unix": asr_web.time.time()}))
        self.returned.write_text(json.dumps({"state": "failed", "error": "KeyboardInterrupt: SIGTERM",
                                            "follower_torque_holding": True}))

    def test_interrupted_return_can_be_closed_repeatedly_then_started(self):
        # Status polling already retired the failed process before Stop arrives.
        for _ in range(2):
            result = asr_web.stop_conversation_motion(self.sid, True)
            self.assertTrue(result["followerTorqueHolding"])
            self.assertFalse(result["returnedToStart"])
        self.assertEqual(asr_web.conversation_motion_get_status()["state"], "idle")
        self.assertIsNone(asr_web.recoverable_conversation_report(self.sid))
        with patch.object(asr_web, "follower_port_available", return_value=True), \
             patch.object(asr_web.subprocess, "Popen", return_value=Mock()) as launch:
            result = asyncio.run(asr_web.conversation_motion_start(
                SimpleNamespace(headers={"x-so101-conversation": "operator-call"})))
        self.assertEqual(result["status"], "starting")
        launch.assert_called_once()

    def test_hold_or_cleanup_failure_is_never_acknowledged_as_safe(self):
        for report in ({"follower_torque_holding": False},
                       {"follower_torque_holding": True, "cleanup_error": "disconnect failed"}):
            self.returned.write_text(json.dumps({"state": "failed", "error": "KeyboardInterrupt: SIGTERM", **report}))
            with self.assertRaises(RuntimeError):
                asr_web.stop_conversation_motion(self.sid)
            self.assertFalse(json.loads(self.returned.read_text()).get("session_closed", False))

    def test_return_retry_publishes_fresh_state_before_process_starts(self):
        def launch(*args, **kwargs):
            self.assertEqual(json.loads(self.returned.read_text()), {"state": "starting"})
            return SimpleNamespace(poll=lambda: None)
        with patch.object(asr_web.subprocess, "Popen", side_effect=launch):
            asyncio.run(asr_web.conversation_motion_return_stopped(
                asr_web.ConversationMotionSession(sessionId=self.sid),
                SimpleNamespace(headers={"x-so101-conversation": "operator-end"})))
        self.assertEqual(asr_web.conversation_motion_status()["state"], "starting")
        self.assertIsNone(asr_web.conversation_motion_status()["error"])

    def test_launch_failure_restores_previous_report(self):
        previous = self.returned.read_text()
        with patch.object(asr_web.subprocess, "Popen", side_effect=OSError("launch failed")):
            with self.assertRaises(OSError):
                asyncio.run(asr_web.conversation_motion_return_stopped(
                    asr_web.ConversationMotionSession(sessionId=self.sid),
                    SimpleNamespace(headers={"x-so101-conversation": "operator-end"})))
        self.assertEqual(self.returned.read_text(), previous)

    def test_finished_latest_session_does_not_resurrect_an_older_call(self):
        newer = self.root / "outputs" / f"conversation-motion-{'b' * 32}.json"
        newer.write_text(json.dumps({"state": "stopped", "follower_torque_holding": True,
                                    "returned_to_start": True, "ended_at_unix": asr_web.time.time()}))
        self.assertIsNone(asr_web.latest_recoverable_conversation())
