"""Check model-specific camera processing without opening physical devices."""

import sys
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import camera_capture_worker as worker


class CameraCaptureWorkerTests(unittest.TestCase):
    def test_missing_x5_uses_fresh_overhead_for_both_molmo_slots(self):
        pair = worker.CameraPair("molmoact2")
        overhead = np.full((720, 1280, 3), 31, np.uint8)
        with patch.object(worker.Path, "exists", autospec=True,
                          side_effect=lambda path: "Insta360" not in str(path)), \
             patch.object(worker.cv2, "VideoCapture") as open_camera, \
             patch.object(pair, "start_streaming"), \
             patch.object(pair.observers["wrist"], "start"), \
             patch("flux3_scene_setup.apply_controls") as controls:
            open_camera.return_value.isOpened.return_value = True
            open_camera.return_value.read.return_value = (True, overhead)
            with tempfile.TemporaryDirectory() as directory, patch.object(worker, "SNAPSHOT_DIR", Path(directory)):
                pair.connect()
                self.assertEqual(pair.camera_sources(), {"cam0": "cam0", "cam1": "cam0"})
                result = pair.capture()
                with np.load(result["path"], allow_pickle=False) as saved:
                    np.testing.assert_array_equal(saved["cam0"], saved["cam1"])
                    self.assertEqual(saved["cam0"].shape, (1, 720, 960, 3))
                self.assertEqual(result["cameraSources"], {"cam0": "cam0", "cam1": "cam0"})
                self.assertEqual(set(result["previews"]), {"cam0", "cam1"})
            controls.assert_called_once()
            open_camera.assert_called_once()
        pair.close()

    def test_missing_overhead_uses_projected_x5_for_both_molmo_slots(self):
        pair = worker.CameraPair("molmoact2")
        panorama = np.full((1440, 2880, 3), 31, np.uint8)
        projected = np.full((720, 960, 3), 42, np.uint8)
        with patch.object(worker.Path, "exists", autospec=True,
                          side_effect=lambda path: "Innomaker" not in str(path)), \
             patch.object(worker.cv2, "VideoCapture") as open_camera, \
             patch.object(pair, "start_streaming"), \
             patch.object(worker, "project_x5", return_value=projected), \
             patch("flux3_scene_setup.apply_controls") as controls:
            open_camera.return_value.isOpened.return_value = True
            open_camera.return_value.read.return_value = (True, panorama)
            pair.connect()
            views = pair.read_views()
            self.assertEqual(pair.camera_sources(), {"cam0": "cam1", "cam1": "cam1"})
            np.testing.assert_array_equal(views["cam0"], projected)
            np.testing.assert_array_equal(views["cam0"], views["cam1"])
            controls.assert_not_called()
        pair.close()

    def test_molmo_refuses_when_no_camera_is_connected(self):
        pair = worker.CameraPair("molmoact2")
        with patch.object(worker.Path, "exists", return_value=False), \
             patch.object(worker.cv2, "VideoCapture") as open_camera, \
             patch("flux3_scene_setup.apply_controls") as controls:
            with self.assertRaisesRegex(RuntimeError, "No MolmoAct2 camera is ready"):
                pair.connect()
            open_camera.assert_not_called()
            controls.assert_not_called()

    def test_molmo_continues_with_fresh_camera_after_other_stream_fails(self):
        pair = worker.CameraPair("molmoact2")
        pair.cameras = {"cam0": object(), "cam1": object()}
        pair.latest["cam0"] = (np.full((720, 1280, 3), 31, np.uint8), time.monotonic())
        pair.failed_roles.add("cam1")
        pair.threads.append(object())
        views, timestamps = pair.read_views(with_meta=True)
        np.testing.assert_array_equal(views["cam0"], views["cam1"])
        self.assertEqual(timestamps["cam0"], timestamps["cam1"])

    def test_startup_error_is_reported_to_parent_and_resources_are_closed(self):
        output = io.StringIO()
        with patch.object(worker, "CameraPair") as pair, \
             patch.object(worker, "PhysicalFrameServer") as server, \
             patch.object(worker.sys, "stdout", output):
            pair.return_value.connect.side_effect = RuntimeError("Insta360 X5 fehlt")
            with self.assertRaisesRegex(RuntimeError, "Insta360 X5 fehlt"):
                worker.serve("molmoact2")
            server.return_value.start.assert_not_called()
            server.return_value.close.assert_called_once()
            pair.return_value.close.assert_called_once()
        self.assertEqual(json.loads(output.getvalue().removeprefix("ERROR_JSON:")),
                         {"error": "Insta360 X5 fehlt"})

    def test_overhead_crop_and_molmo_x5_projection_are_separate(self):
        pair = worker.CameraPair("molmoact2")
        raw = {
            "cam0": np.full((720, 1280, 3), 30, np.uint8),
            "cam1": np.full((1440, 2880, 3), 40, np.uint8),
        }
        raw["cam0"][:, :160] = 200
        with (patch.object(pair, "read_raw", return_value=raw),
              patch.object(worker, "project_x5", return_value=np.full((720, 960, 3), 50, np.uint8)) as project):
            views = pair.read_views()
        self.assertEqual(set(views), {"cam0", "cam1"})
        self.assertEqual(views["cam0"].shape, (720, 960, 3))
        self.assertEqual(views["cam1"].shape, (720, 960, 3))
        self.assertEqual(int(views["cam0"][0, 0, 0]), 30)
        project.assert_called_once()

    def test_molmo_capture_preserves_one_prepared_camera_pair(self):
        pair = worker.CameraPair("molmoact2")
        count = 0

        def views(*, after=0.0, with_meta=False):
            nonlocal count
            count += 1
            result = {"cam0": np.full((3, 4, 3), count, np.uint8),
                      "cam1": np.full((3, 4, 3), 100 + count, np.uint8)}
            return (result, {"cam0": float(count), "cam1": float(count)}) if with_meta else result

        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "SNAPSHOT_DIR", Path(directory)), \
             patch.object(pair, "read_views", side_effect=views):
            result = pair.capture()
            with np.load(result["path"], allow_pickle=False) as saved:
                self.assertEqual(saved["cam0"].shape, (1, 3, 4, 3))
                self.assertEqual(saved["cam0"][:, 0, 0, 0].tolist(), [1])
                self.assertEqual(saved["cam1"][:, 0, 0, 0].tolist(), [101])
            self.assertEqual(result["frames"], 1)
            self.assertEqual(set(result["previews"]), {"cam0", "cam1"})


if __name__ == "__main__":
    unittest.main()
