"""Concurrent policy warmup and conversation task handoff, without hardware."""

import asyncio
import io
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_web
from model_sessions import ModelSession


class ObservedLock:
    def __init__(self):
        self.lock = threading.Lock()
        self.waiting = threading.Event()

    def acquire(self, *args, **kwargs):
        acquired = self.lock.acquire(*args, **kwargs)
        if not acquired:
            self.waiting.set()
        return acquired

    def release(self):
        self.lock.release()


class ConversationTaskWarmupTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(directory)
        (self.root / "outputs").mkdir()
        self.session_id = "a" * 32
        self.motion = {"sessionId": self.session_id, "state": "holding",
                       "active": True, "returnRequested": False}
        self.lock = ObservedLock()
        for name, value in {
            "ROOT": self.root, "_policy_lock": self.lock,
            "_active_task": None, "_last_task": None,
            "_conversation_task_calls": {}, "_conversation_robot_reset_session": None,
        }.items():
            self.stack.enter_context(patch.object(asr_web, name, value))
        self.stack.enter_context(patch.object(asr_web, "conversation_motion_status",
                                            side_effect=lambda: dict(self.motion)))
        self.stack.enter_context(patch.object(asr_web.face_tracking_session, "disable"))
        self.request = asr_web.ConversationTaskRequest(
            sessionId=self.session_id, instruction="Move the ball", callId="call-1")

    def test_task_waits_for_real_preload_route_and_reuses_loaded_worker(self):
        """The actual ModelSession must send warm only once across the handoff."""
        policy = ModelSession()
        warm_started, finish_warm = threading.Event(), threading.Event()
        pose = dict.fromkeys(("shoulder_pan", "shoulder_lift", "elbow_flex",
                              "wrist_flex", "wrist_roll", "gripper"), 0.0)
        commands = []

        def start_worker(model):
            policy._model_id = model
            policy._process = SimpleNamespace(poll=lambda: None, stdin=io.BytesIO())

        def warm_result(_timeout):
            warm_started.set()
            if not finish_warm.wait(3):
                raise AssertionError("Test did not release warmup")
            return {"model": "molmoact2", "ready": True, "hardwareCommands": False}

        async def inline(function, *args):
            return function(*args)

        def owner(_session, command):
            commands.append(command["op"])
            if command["op"] == "snapshot":
                Path(command["observation_path"]).touch()
                return {"status": "observed", "model": "molmoact2",
                        "observation_path": command["observation_path"], "state": pose}
            if command["op"] == "execute":
                asr_web._active_task["stop"].set()
                return {"status": "executed", "executedActions": 1}
            return {"status": command["op"], "speechGripperAvailable": True}

        with patch.object(asr_web, "policy_session", policy), \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
             patch.object(policy, "_start", side_effect=start_worker) as start, \
             patch.object(policy, "_next_record", side_effect=warm_result) as record, \
             patch.object(asr_web, "available_models", return_value=[{
                 "id": "molmoact2", "available": True}]), \
             patch.object(asr_web, "camera_session", SimpleNamespace(select=Mock())), \
             patch.object(asr_web, "conversation_holder_command", side_effect=owner), \
             patch.object(asr_web, "predict_physical_chunk", return_value={"actions": [pose]}), \
             ThreadPoolExecutor(max_workers=2) as pool:
            warm = pool.submit(asyncio.run, asr_web.conversation_realtime_molmo_preload(
                SimpleNamespace(headers={"x-so101-conversation": "operator-call"}),
                asr_web.RealtimePreloadRequest(sessionId=self.session_id)))
            try:
                self.assertTrue(warm_started.wait(2))
                task = pool.submit(asr_web.start_conversation_task, self.request, timeout_s=3)
                self.assertTrue(self.lock.waiting.wait(2))
                self.assertFalse(task.done())
                self.assertIsNone(asr_web._active_task)
                self.assertEqual(commands, [])
                # The pending request must not block reset/face-tracking's guard.
                self.assertTrue(asr_web._conversation_task_start_guard.acquire(timeout=1))
                asr_web._conversation_task_start_guard.release()
            finally:
                finish_warm.set()
            self.assertTrue(warm.result(timeout=3)["ready"])
            self.assertEqual(task.result(timeout=3)["taskRun"]["model"], "molmoact2")
            self.assertTrue(self.lock.acquire(timeout=3))
            self.lock.release()
            self.assertEqual(commands, ["task_active", "snapshot", "execute", "task_inactive"])
            start.assert_called_once_with("molmoact2")
            record.assert_called_once()
            self.assertEqual(policy._process.stdin.getvalue(), b'{"op":"warm"}\n')

    def test_wait_is_cancelled_when_conversation_returns_stops_or_changes(self):
        for change in ({"returnRequested": True}, {"active": False},
                       {"sessionId": "b" * 32}, {"state": "stopped"}):
            with self.subTest(change=change), \
                 patch.object(asr_web, "physical_task_loop") as worker, \
                 ThreadPoolExecutor(max_workers=1) as pool:
                original = dict(self.motion)
                self.lock.waiting.clear()
                self.lock.acquire()
                try:
                    task = pool.submit(asr_web.start_conversation_task, self.request, timeout_s=2)
                    self.assertTrue(self.lock.waiting.wait(1))
                    self.motion.update(change)
                    with self.assertRaises(HTTPException) as cancelled:
                        task.result(timeout=1)
                    self.assertEqual(cancelled.exception.status_code, 409)
                    self.assertIsNone(asr_web._active_task)
                    worker.assert_not_called()
                finally:
                    self.lock.release()
                    self.motion = original

    def test_wait_rechecks_local_tool_authorization(self):
        revoked = threading.Event()

        def authorize():
            if revoked.is_set():
                raise RuntimeError("The local task was cancelled.")

        with patch.object(asr_web, "physical_task_loop") as worker, \
             ThreadPoolExecutor(max_workers=1) as pool:
            self.lock.acquire()
            try:
                task = pool.submit(asr_web.start_conversation_task, self.request,
                                   authorize=authorize, timeout_s=2)
                self.assertTrue(self.lock.waiting.wait(1))
                revoked.set()
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    task.result(timeout=1)
                worker.assert_not_called()
                self.assertIsNone(asr_web._active_task)
            finally:
                self.lock.release()

    def test_wait_timeout_does_not_release_another_operations_lock(self):
        self.lock.acquire()
        try:
            with self.assertRaises(HTTPException) as expired:
                asr_web.start_conversation_task(self.request, timeout_s=0)
            self.assertEqual(expired.exception.status_code, 504)
            self.assertFalse(self.lock.acquire(blocking=False))
            self.assertIsNone(asr_web._active_task)
        finally:
            self.lock.release()

    def test_unrelated_active_task_is_rejected_without_waiting(self):
        with patch.object(asr_web, "_active_task", {
                "conversationSessionId": "b" * 32, "model": "molmoact2",
                "stop": threading.Event()}):
            with self.assertRaises(HTTPException) as busy:
                asr_web.start_conversation_task(self.request)
            self.assertEqual(busy.exception.status_code, 409)
            self.assertFalse(self.lock.waiting.is_set())


if __name__ == "__main__":
    unittest.main()
