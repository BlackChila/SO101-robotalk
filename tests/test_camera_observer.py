"""A display-only wrist must never enter or block the policy camera pair."""
import sys
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from camera_observer import OptionalCameraObserver
from camera_profiles import camera_profile
import camera_capture_worker as worker


class CameraObserverTests(unittest.TestCase):
    def observer(self):
        config = camera_profile("molmoact2")["observer_cameras"]["wrist"]
        return OptionalCameraObserver(config)

    def test_missing_or_unopenable_wrist_is_optional_and_releases_resources(self):
        observer = self.observer()
        with patch("camera_observer.Path.exists", return_value=False), \
             patch("camera_observer.cv2.VideoCapture") as capture:
            observer.start()
            capture.assert_not_called()
            self.assertFalse(observer.available)
            self.assertIsNone(observer.snapshot())
            self.assertIn("nicht verbunden", observer.error)
        with patch("camera_observer.Path.exists", return_value=True), \
             patch("flux3_scene_setup.apply_controls"), \
             patch("camera_observer.cv2.VideoCapture") as capture:
            capture.return_value.isOpened.return_value = False
            observer.start()
            capture.return_value.release.assert_called_once()
            self.assertFalse(observer.available)

    def test_observer_crops_preview_but_preserves_raw_tracking_frame(self):
        observer = self.observer()
        observer.camera = object()
        observer.error = None
        observer.latest = (np.full((1080, 1920, 3), 40, np.uint8), time.monotonic())
        self.assertEqual(observer.snapshot().shape, (1080, 1440, 3))
        self.assertEqual(observer.snapshot(raw=True).shape, (1080, 1920, 3))
        observer.latest = (observer.latest[0], time.monotonic() - 1)
        self.assertIsNone(observer.snapshot())
        with self.assertRaises(TimeoutError):
            observer.snapshot(after=time.monotonic(), timeout_s=0)
        observer.error = "camera disconnected"
        self.assertIsNone(observer.snapshot())
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            observer.snapshot(after=time.monotonic())

    def test_policy_snapshot_contains_only_cam0_and_cam1_even_with_failed_wrist(self):
        pair = worker.CameraPair("molmoact2")
        wrist = Mock(available=True, error=None)
        wrist.snapshot.side_effect = RuntimeError("wrist failed")
        pair.observers = {"wrist": wrist}
        views = {"cam0": np.full((3, 4, 3), 40, np.uint8), "cam1": np.full((3, 4, 3), 50, np.uint8)}
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "SNAPSHOT_DIR", Path(directory)), \
             patch.object(pair, "read_views", side_effect=lambda **kw: (views, {"cam0": 1, "cam1": 1}) if kw.get("with_meta") else views):
            capture = pair.capture()
            with np.load(capture["path"]) as saved:
                self.assertEqual(set(saved.files), {"cam0", "cam1"})
            wrist.snapshot.assert_not_called()
            preview = pair.preview()
            self.assertEqual(set(preview["previews"]), {"cam0", "cam1"})
            self.assertEqual(preview["observerPreviews"], {})
        self.assertEqual(set(pair.profile["cameras"]), {"cam0", "cam1"})
        self.assertEqual(set(pair.profile["slots"]), {"cam0", "cam1"})

    def test_observer_brightness_uses_wrist_device_and_requires_its_fresh_frame(self):
        pair = worker.CameraPair("molmoact2")
        pair.observers["wrist"] = Mock(available=True)
        control = {"min": -64, "max": 64, "step": 1, "default": 0, "value": 0}
        pair.brightness["wrist"] = control
        device = pair.profile["observer_cameras"]["wrist"]["path"]
        with patch.object(worker, "probe_brightness", return_value=control), \
             patch.object(worker, "set_brightness", return_value={**control, "value": -20}) as write, \
             patch.object(pair, "preview", return_value={"observerPreviews": {"wrist": {"jpeg": "frame"}}}) as preview, \
             patch.object(worker, "save_brightness") as save:
            pair.set_camera_brightness("wrist", -20)
            write.assert_called_once_with(device, -20, control)
            save.assert_called_once_with(device, -20)
            self.assertGreater(preview.call_args.kwargs["observer_after"], time.monotonic())
            self.assertNotIn("after", preview.call_args.kwargs)

    def test_conversation_profile_keeps_each_camera_optional_and_never_reads_policy_pair(self):
        pair = worker.CameraPair("conversation")
        self.assertEqual(pair.profile["cameras"], {})
        self.assertEqual(pair.profile["slots"], {})
        pair.observers = {
            "cam0": Mock(available=False, error="missing", snapshot=Mock(return_value=None)),
            "cam1": Mock(available=False, error="missing", snapshot=Mock(return_value=None)),
            "wrist": Mock(available=True, error=None, snapshot=Mock(return_value=np.zeros((3, 4, 3), np.uint8))),
        }
        with patch.object(pair, "read_views", side_effect=AssertionError("policy pair accessed")):
            pair.connect()
            for observer in pair.observers.values():
                observer.start.assert_called_once()
            result = pair.preview()
        self.assertEqual(result["previews"], {})
        self.assertEqual(set(result["observerPreviews"]), {"wrist"})
        with self.assertRaisesRegex(ValueError, "previews only"):
            pair.capture()

    def test_conversation_worker_does_not_publish_an_inference_stream_or_capture(self):
        output = io.StringIO()
        with patch.object(worker, "CameraPair") as pair, \
             patch.object(worker, "PhysicalFrameServer") as server, \
             patch.object(worker.sys, "stdout", output), \
             patch.object(worker.sys, "stdin", io.StringIO('{"op":"capture"}\n{"op":"stop"}\n')):
            worker.serve("conversation")
        server.return_value.start.assert_not_called()
        server.return_value.close.assert_not_called()
        pair.return_value.capture.assert_not_called()
        records = output.getvalue().splitlines()
        self.assertTrue(json.loads(records[0].split(":", 1)[1])["ready"])
        self.assertIn("previews only", json.loads(records[1].split(":", 1)[1])["error"])

    def test_conversation_x5_uses_raw_panorama_and_saved_projection(self):
        pair = worker.CameraPair("conversation")
        frame = np.zeros((1440, 2880, 3), np.uint8)
        pair.observers = {"cam1": Mock(available=True, error=None, snapshot=Mock(return_value=frame))}
        with patch.object(worker, "project_x5", return_value=np.zeros((720, 960, 3), np.uint8)) as project:
            result = pair.preview()
        pair.observers["cam1"].snapshot.assert_called_once_with(after=0.0, raw=True)
        project.assert_called_once_with(frame, pair.profile["x5_projection"])
        self.assertEqual(result["observerPreviews"]["cam1"]["width"], 960)
        self.assertIsNotNone(result["insta360View"])

    def test_conversation_setting_waits_only_for_the_adjusted_camera(self):
        pair = worker.CameraPair("conversation")
        missing = Mock(available=False, error="missing", snapshot=Mock(return_value=None))
        wrist = Mock(available=True, error=None, snapshot=Mock(return_value=np.zeros((3, 4, 3), np.uint8)))
        pair.observers = {"cam0": missing, "wrist": wrist}
        result = pair.settings_preview("wrist")
        missing.snapshot.assert_called_once_with(after=0.0)
        self.assertGreater(wrist.snapshot.call_args.kwargs["after"], time.monotonic())
        self.assertEqual(set(result["observerPreviews"]), {"wrist"})

    def test_saved_brightness_restores_observer_on_startup(self):
        pair = worker.CameraPair("molmoact2")
        pair.observers["wrist"] = Mock(available=True)
        device = pair.profile["observer_cameras"]["wrist"]["path"]
        control = {"min": -64, "max": 64, "step": 1, "default": 0, "value": 0}
        with patch.object(worker, "load_brightness", return_value={device: -20}), \
             patch.object(worker, "probe_brightness", return_value=control), \
             patch.object(worker, "set_brightness", return_value={**control, "value": -20}) as write:
            pair.initialize_brightness()
            write.assert_called_once_with(device, -20, control)
            self.assertEqual(pair.brightness_metadata()["wrist"]["value"], -20)


if __name__ == "__main__":
    unittest.main()
