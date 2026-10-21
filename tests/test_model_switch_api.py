"""Test policy-session API handlers without an ASR model or robot."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_web  # noqa: E402
from shared_camera_stream import PhysicalCameraLeaseBusy


async def inline(function, *args, **kwargs):
    return function(*args, **kwargs)


class ModelSwitchApiTests(unittest.TestCase):
    def test_removed_models_are_rejected_before_hardware_or_worker_access(self) -> None:
        request = asr_web.ModelRequest(prompt="Move the ball")
        browser = type("Browser", (), {"headers": {"x-so101-execute": "operator-ptt"}})()
        with (patch.object(asr_web.camera_session, "select") as camera,
              patch.object(asr_web.policy_session, "preload") as policy,
              patch.object(asr_web, "run_model_inference") as infer,
              patch.object(asr_web, "holder_command") as holder):
            for model in ("flux3", "g05"):
                calls = (
                    lambda: asr_web.select_model(model),
                    lambda: asr_web.select_camera_model(model),
                    lambda: asr_web.reload_camera_model(model),
                    lambda: asr_web.camera_preview(model),
                    lambda: asr_web.model_infer(model, request),
                    lambda: asr_web.execute_model_task(model, request, browser),
                )
                for call in calls:
                    with self.subTest(model=model, operation=call), self.assertRaises(asr_web.HTTPException) as denied:
                        asyncio.run(call())
                    self.assertEqual(denied.exception.status_code, 404)
        camera.assert_not_called()
        policy.assert_not_called()
        infer.assert_not_called()
        holder.assert_not_called()

    def test_stop_waits_for_worker_exit(self) -> None:
        asr_model = object()
        with (
            patch.object(asr_web, "run_in_threadpool", inline),
            patch.object(asr_web.policy_session, "stop") as stop,
            patch.object(asr_web, "_model", asr_model),
        ):
            self.assertEqual(asyncio.run(asr_web.stop_model_session()), {"status": "stopped"})
            stop.assert_called_once()
            self.assertIs(asr_web._model, asr_model)

    def test_each_task_uses_selected_policy(self) -> None:
        with (
            patch.object(asr_web, "run_in_threadpool", inline),
            patch.object(asr_web, "reset_state", return_value=("idle", None)),
            patch.object(asr_web, "run_model_inference") as infer,
        ):
            for model_id in ("molmoact2",):
                infer.return_value = {"model": model_id, "hardwareCommands": False}
                result = asyncio.run(asr_web.model_infer(model_id, asr_web.ModelRequest(prompt=" Ziel ")))
                self.assertEqual(result["model"], model_id)
                infer.assert_called_with(model_id, "Ziel")

    def test_live_task_requires_camera_capture_and_passes_it_to_worker(self) -> None:
        capture = {"model": "molmoact2", "path": "/tmp/live.npz", "geometry": "overhead_x5_4x3",
                   "frames": 1, "capturedAt": 123.0}
        with (
            patch.object(asr_web, "run_in_threadpool", inline),
            patch.object(asr_web, "reset_state", return_value=("idle", None)),
            patch.object(asr_web.camera_session, "capture", return_value=capture) as camera,
            patch.object(asr_web, "run_model_inference", return_value={
                "model": "molmoact2", "hardwareCommands": False}) as infer,
        ):
            result = asyncio.run(asr_web.model_infer(
                "molmoact2", asr_web.ModelRequest(prompt="Ball", liveCamera=True)))
            camera.assert_called_once_with("molmoact2")
            infer.assert_called_once_with("molmoact2", "Ball", camera_npz="/tmp/live.npz")
            self.assertEqual(result["cameraCapture"]["geometry"], "overhead_x5_4x3")

    def test_camera_selection_and_preview_use_matching_model(self) -> None:
        with (
            patch.object(asr_web, "run_in_threadpool", inline),
            patch.object(asr_web, "reset_state", return_value=("idle", None)),
            patch.object(asr_web.camera_session, "select", return_value={"model": "molmoact2"}) as select,
            patch.object(asr_web.camera_session, "preview", return_value={"model": "molmoact2"}) as preview,
        ):
            self.assertEqual(asyncio.run(asr_web.select_camera_model("molmoact2"))["model"], "molmoact2")
            self.assertEqual(asyncio.run(asr_web.camera_preview("molmoact2"))["model"], "molmoact2")
            select.assert_called_once_with("molmoact2")
            preview.assert_called_once_with("molmoact2")

    def test_preview_does_not_block_model_switch_lock(self) -> None:
        with (patch.object(asr_web, "run_in_threadpool", inline),
              patch.object(asr_web.camera_session, "preview", return_value={"model": "molmoact2"})):
            self.assertTrue(asr_web._policy_lock.acquire(blocking=False))
            try:
                self.assertEqual(asyncio.run(asr_web.camera_preview("molmoact2"))["model"], "molmoact2")
            finally:
                asr_web._policy_lock.release()

    def test_physical_camera_lease_rejects_switch_and_shadow_inference(self) -> None:
        with (patch.object(asr_web, "require_no_physical_client",
                           side_effect=PhysicalCameraLeaseBusy("physical active")),
              patch.object(asr_web, "reset_state", return_value=("idle", None))):
            with self.assertRaises(asr_web.HTTPException) as switch:
                asyncio.run(asr_web.select_camera_model("molmoact2"))
            self.assertEqual(switch.exception.status_code, 409)
            with self.assertRaises(asr_web.HTTPException) as infer:
                asyncio.run(asr_web.model_infer("molmoact2", asr_web.ModelRequest(prompt="Ball")))
            self.assertEqual(infer.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
