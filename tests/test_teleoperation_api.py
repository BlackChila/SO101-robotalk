"""UI teleoperation routes must never actuate without an operator click."""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_web  # noqa: E402


class TeleoperationApiTests(unittest.TestCase):
    @staticmethod
    async def inline_threadpool(function, *args, **kwargs):
        return function(*args, **kwargs)

    def test_start_requires_click_and_accepts_fresh_camera_frames(self) -> None:
        browser = SimpleNamespace(headers={"x-so101-teleop": "operator-click"})
        preview = {"capturedAt": asr_web.time.time(), "cameraSources": {"cam0": "cam0", "cam1": "cam1"},
                   "previews": {"cam0": {"jpeg": "a"}, "cam1": {"jpeg": "b"}}}
        camera = SimpleNamespace(model_id="molmoact2", preview=lambda _: preview)
        with patch.object(asr_web, "teleop_blocker", return_value=None), \
             patch.object(asr_web, "camera_session", camera), \
             patch.object(asr_web, "run_in_threadpool", self.inline_threadpool), \
             patch.object(asr_web.teleoperation_session, "start", return_value={"state": "active"}) as start:
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.start_teleoperation(SimpleNamespace(headers={})))
            self.assertEqual(denied.exception.status_code, 403)
            start.assert_not_called()
            result = asyncio.run(asr_web.start_teleoperation(browser))
            self.assertEqual(result["state"], "active")
            self.assertNotIn("warning", result)
            start.assert_called_once_with()

    def test_camera_problems_warn_without_blocking_start(self) -> None:
        browser = SimpleNamespace(headers={"x-so101-teleop": "operator-click"})
        fresh = {"capturedAt": asr_web.time.time(),
                 "previews": {"cam0": {"jpeg": "a"}, "cam1": {"jpeg": "b"}},
                 "cameraSources": {"cam0": "overhead", "cam1": "x5"}}
        cases = [
            (None, None, None, "Keine Live-Kameras"),
            ("molmoact2", {**fresh, "capturedAt": 0}, None, "nicht frisch"),
            ("molmoact2", {**fresh, "previews": {"cam0": {"jpeg": "a"}}}, None, "unvollständig"),
            ("molmoact2", {**fresh, "cameraSources": {"cam0": "cam0", "cam1": "cam0"}},
             None, "unabhängigen Livebilder"),
            ("molmoact2", None, RuntimeError("Kamera getrennt"), "Kamera getrennt"),
            ("molmoact2", None, OSError("USB-Fehler"), "USB-Fehler"),
            ("molmoact2", None, TimeoutError("Zeitlimit"), "Zeitlimit"),
        ]
        for model, preview, error, warning in cases:
            with self.subTest(warning=warning):
                camera = SimpleNamespace(model_id=model, preview=Mock(return_value=preview, side_effect=error))
                with patch.object(asr_web, "teleop_blocker", return_value=None), \
                     patch.object(asr_web, "camera_session", camera), \
                     patch.object(asr_web, "run_in_threadpool", self.inline_threadpool), \
                     patch.object(asr_web.teleoperation_session, "start", return_value={
                         "state": "active", "message": "Follower folgt dem Leader."}) as start:
                    result = asyncio.run(asr_web.start_teleoperation(browser))
                self.assertEqual(result["state"], "active")
                self.assertIn(warning, result["warning"])
                self.assertIn("Warnung:", result["message"])
                self.assertIn("Follower folgt dem Leader.", result["message"])
                start.assert_called_once_with()
                if model is None:
                    camera.preview.assert_not_called()

    def test_camera_warning_does_not_bypass_controller_blockers(self) -> None:
        browser = SimpleNamespace(headers={"x-so101-teleop": "operator-click"})
        for blockers in (["Follower belegt."], [None, "Follower belegt."]):
            with self.subTest(blockers=blockers), \
                 patch.object(asr_web, "teleop_blocker", side_effect=blockers), \
                 patch.object(asr_web, "camera_session", SimpleNamespace(model_id=None)), \
                 patch.object(asr_web.teleoperation_session, "start") as start:
                with self.assertRaises(HTTPException) as busy:
                    asyncio.run(asr_web.start_teleoperation(browser))
                self.assertEqual(busy.exception.status_code, 409)
                start.assert_not_called()

    def test_no_camera_profile_does_not_disable_teleoperation(self) -> None:
        with patch.object(asr_web.teleoperation_session, "status", return_value={"occupied": False}), \
             patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "_return_running", False), \
             patch.object(asr_web, "torque_state", return_value=("idle", None)), \
             patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False}), \
             patch.object(asr_web, "task_status", return_value=None), \
             patch.object(asr_web, "_policy_lock", SimpleNamespace(locked=lambda: False)), \
             patch.object(asr_web, "camera_session", SimpleNamespace(model_id=None)), \
             patch.object(asr_web, "follower_port_available", return_value=True), \
             patch.object(asr_web, "LEADER_PORT", Path(__file__)), \
             patch.object(asr_web, "FLUX_PYTHON", Path(sys.executable)), \
             patch.object(asr_web, "TELEOP_RUNNER", Path(__file__)):
            self.assertIsNone(asr_web.teleop_blocker())
            with patch.object(asr_web, "follower_port_available", return_value=False):
                self.assertIn("nicht verbunden", asr_web.teleop_blocker())

    def test_busy_teleoperation_blocks_reset_and_model_motion(self) -> None:
        with patch.object(asr_web.teleoperation_session, "status", return_value={"occupied": True}):
            self.assertIn("Teleoperation", asr_web.reset_blocker())
            request = asr_web.ModelRequest(prompt="test", liveCamera=True)
            browser = SimpleNamespace(headers={"x-so101-execute": "operator-ptt"})
            with patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False}):
                with self.assertRaises(HTTPException) as busy:
                    asyncio.run(asr_web.execute_model_task("molmoact2", request, browser))
            self.assertEqual(busy.exception.status_code, 409)

    def test_stop_requires_click_and_calls_graceful_process_stop(self) -> None:
        with patch.object(asr_web.teleoperation_session, "stop", return_value={
            "state": "stopped", "holdVerified": True}) as stop, \
             patch.object(asr_web, "run_in_threadpool", self.inline_threadpool):
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.stop_teleoperation(SimpleNamespace(headers={})))
            self.assertEqual(denied.exception.status_code, 403)
            self.assertTrue(asyncio.run(asr_web.stop_teleoperation(SimpleNamespace(
                headers={"x-so101-teleop": "operator-click"})))["holdVerified"])
            stop.assert_called_once_with()

    @patch.object(asr_web, "FLUX_PYTHON", Path(sys.executable))
    def test_explicit_torque_off_stops_ui_teleoperation_first(self) -> None:
        browser = SimpleNamespace(headers={"x-so101-torque": "operator-click"})
        with patch.object(asr_web.teleoperation_session, "status", return_value={"occupied": True}), \
             patch.object(asr_web.teleoperation_session, "stop", return_value={"state": "stopped"}) as stop, \
             patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False}), \
             patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "turn_off_unmanaged", return_value={"status": "off"}) as turn_off, \
             patch.object(asr_web, "run_in_threadpool", self.inline_threadpool), \
             patch.object(asr_web, "_torque_state", "idle"), \
             patch.object(asr_web, "_torque_process", None), \
             patch.object(asr_web, "_torque_report_path", None), \
             patch.object(asr_web, "_torque_verified_off", False):
            self.assertEqual(asyncio.run(asr_web.torque_off(browser))["status"], "off")
            stop.assert_called_once_with()
            turn_off.assert_called_once()


if __name__ == "__main__":
    unittest.main()
