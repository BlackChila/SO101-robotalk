"""Exposure validation, startup configuration and rollback without hardware."""
import sys
import fcntl
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import camera_exposure as exposure
import camera_capture_worker as worker
from camera_profiles import camera_profile
from live_camera_session import LiveCameraSession
import shared_camera_stream as stream

CONTROL = {"min": 1, "max": 333, "step": 1, "default": 156, "value": 80}


class CameraExposureTests(unittest.TestCase):
    def test_supported_range_and_manual_mode_readback(self):
        with patch.object(exposure, "probe_control", return_value={**CONTROL, "max": 5000}):
            self.assertEqual(exposure.probe_exposure("/dev/camera")["max"], 333)
        with patch.object(exposure, "probe_control", return_value=None):
            self.assertIsNone(exposure.probe_exposure("/dev/x5"))
        with patch.object(exposure, "probe_exposure", return_value=CONTROL.copy()), \
             patch.object(exposure.subprocess, "run", return_value=SimpleNamespace(stdout="auto_exposure: 1 (Manual Mode)\n")) as run:
            self.assertEqual(exposure.set_exposure("/dev/camera", 80, CONTROL), CONTROL)
            self.assertEqual(run.call_args_list[0].args[0][-1], "auto_exposure=1,exposure_time_absolute=80")
            with self.assertRaises(RuntimeError):
                exposure.set_exposure("/dev/camera", 81, CONTROL)
            run.return_value.stdout = "auto_exposure: 3\n"
            with self.assertRaises(RuntimeError):
                exposure.set_exposure("/dev/camera", 80, CONTROL)

    def test_validation_and_persistence(self):
        for value in [True, 0, 334, 5000, 0.5, "50"]:
            with self.assertRaises(ValueError):
                exposure.validate_exposure(value, CONTROL)
        with tempfile.TemporaryDirectory() as directory, patch.object(exposure, "SETTINGS_PATH", Path(directory) / "saved.json"):
            exposure.save_exposure("/dev/overhead", 80)
            exposure.save_exposure("/dev/wrist", 50)
            self.assertEqual(exposure.load_exposure(), {"/dev/overhead": 80, "/dev/wrist": 50})

    def test_saved_exposure_overrides_baseline_and_reset_uses_profile(self):
        pair = worker.CameraPair("molmoact2")
        pair.cameras = {"cam0": object()}
        device = pair.profile["cameras"]["cam0"]["path"]
        with patch.object(worker, "load_exposure", return_value={device: 40}), \
             patch.object(worker, "probe_exposure", return_value=CONTROL.copy()), \
             patch.object(worker, "set_exposure", return_value={**CONTROL, "value": 40}) as write:
            pair.initialize_exposure()
            write.assert_called_once_with(device, 40, CONTROL)
            self.assertEqual(pair.exposure_metadata()["cam0"], {**CONTROL, "default": 150, "value": 40})

    def test_session_refuses_physical_lease_and_stale_profile(self):
        session = LiveCameraSession()
        with tempfile.TemporaryDirectory() as directory:
            lease_path = Path(directory) / "lease"
            with lease_path.open("a+b") as lease, patch.object(stream, "LEASE_PATH", lease_path), \
                 patch.object(session, "_call") as call:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(stream.PhysicalCameraLeaseBusy):
                    session.set_camera_exposure("molmoact2", "cam0", 80)
                call.assert_not_called()
                fcntl.flock(lease, fcntl.LOCK_UN)
                with self.assertRaisesRegex(RuntimeError, "nicht aktiv"):
                    session.set_camera_exposure("molmoact2", "cam0", 80)
                call.assert_not_called()
                session._model_id = "molmoact2"
                session._process = Mock()
                session._process.poll.return_value = None
                session.set_camera_exposure("molmoact2", "cam0", 80)
                call.assert_called_once_with("exposure", role="cam0", value=80)

    def test_failed_save_or_black_preview_restores_actual_exposure(self):
        pair = worker.CameraPair("molmoact2")
        pair.cameras = {"cam0": object()}
        pair.exposure = {"cam0": CONTROL.copy()}
        with patch.object(worker, "probe_exposure", return_value=CONTROL.copy()), \
             patch.object(worker, "set_exposure", side_effect=lambda device, value, ctrl: {**ctrl, "value": value}) as write, \
             patch.object(pair, "preview", return_value={"cameraExposure": {"cam0": CONTROL}}) as preview, \
             patch.object(worker, "save_exposure") as save:
            pair.set_camera_exposure("cam0", 40)
            self.assertGreater(preview.call_args.kwargs["after"], 0)
            save.assert_called_once()
            save.side_effect = OSError("disk full")
            with self.assertRaises(OSError):
                pair.set_camera_exposure("cam0", 30)
            self.assertEqual(write.call_args.args[1], 80)
            save.side_effect = None
            preview.side_effect = [RuntimeError("black image"), {"cameraExposure": {"cam0": CONTROL}}]
            with self.assertRaisesRegex(RuntimeError, "black image"):
                pair.set_camera_exposure("cam0", 1)
            self.assertEqual(write.call_args.args[1], 80)
            self.assertEqual(pair.adjusting_exposure, set())
            with self.assertRaises(RuntimeError):
                pair.set_camera_exposure("wrist", 40)

    def test_dark_transition_during_adjustment_does_not_disable_molmo_source(self):
        for adjusting in [False, True]:
            pair = worker.CameraPair("molmoact2")
            config = pair.profile["cameras"]["cam0"]
            shape = (config["height"], config["width"], 3)
            frames = iter([np.zeros(shape, np.uint8), np.full(shape, 40, np.uint8)])
            def read():
                frame = next(frames)
                if frame[0, 0, 0]:
                    pair.stop_event.set()
                return True, frame
            camera = Mock()
            camera.read.side_effect = read
            pair.cameras = {"cam0": camera}
            if adjusting:
                pair.adjusting_exposure.add("cam0")
            pair._capture_loop("cam0", camera)
            self.assertEqual("cam0" in pair.failed_roles, not adjusting)
            if adjusting:
                self.assertEqual(pair.latest["cam0"][0][0, 0, 0], 40)


if __name__ == "__main__":
    unittest.main()
