"""Camera-only projection, persistence and physical-stream lease regression checks."""
import fcntl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import insta360_view as settings
import camera_capture_worker as worker
import shared_camera_stream as stream
from camera_profiles import camera_profile
from live_camera_session import LiveCameraSession


class Insta360ViewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "view.json"
        self.patcher = patch.object(settings, "SETTINGS_PATH", self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_saved_direction_and_zoom_survive_new_profiles_and_keep_4x3_output(self):
        self.assertEqual(settings.load_view(), settings.DEFAULT_VIEW)
        view = {"yaw": -120.5, "pitch": -35, "roll": 0, "zoom": 1.3}
        settings.save_view(view)
        profile = camera_profile("molmoact2")
        self.assertEqual(profile["x5_view"], view)
        self.assertEqual(profile["x5_projection"],
                         "v360=input=e:output=flat:yaw=-120.5:pitch=-35:roll=0:h_fov=40:v_fov=30:w=960:h=720")
        self.assertEqual(profile["cameras"]["cam1"]["width"], 2880)
        self.assertEqual(profile["cameras"]["cam1"]["height"], 1440)

    def test_existing_saved_direction_starts_at_one_times_zoom(self):
        self.path.write_text('{"yaw": -4.5, "pitch": -11.5, "roll": 2.5}\n')
        self.assertEqual(settings.load_view(),
                         {"yaw": -4.5, "pitch": -11.5, "roll": 2.5, "zoom": 1.0})

    def test_invalid_values_and_resolution_changes_are_rejected(self):
        for value in [True, "10", float("nan"), float("inf"), 181, -181]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.save_view({**settings.DEFAULT_VIEW, "yaw": value})
        for invalid in [{**settings.DEFAULT_VIEW, "pitch": 91},
                        {**settings.DEFAULT_VIEW, "zoom": 0.9},
                        {**settings.DEFAULT_VIEW, "zoom": 2.1},
                        {**settings.DEFAULT_VIEW, "zoom": True},
                        {**settings.DEFAULT_VIEW, "width": 320}, {}, None]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                settings.validate_view(invalid)
        self.assertFalse(self.path.exists())

    def test_real_ffmpeg_projection_moves_cutout_without_resizing(self):
        panorama = np.zeros((1440, 2880, 3), dtype=np.uint8)
        panorama[:, :, 0] = np.linspace(0, 255, 2880, dtype=np.uint8)[None, :]
        panorama[:, :, 1] = np.linspace(0, 255, 1440, dtype=np.uint8)[:, None]
        base = worker.project_x5(panorama, settings.projection_filter({"yaw": 0, "pitch": 0, "roll": 0}))
        for axis in ("yaw", "pitch", "roll"):
            view = {"yaw": 0, "pitch": 0, "roll": 0, axis: 45}
            result = worker.project_x5(panorama, settings.projection_filter(view))
            self.assertEqual(result.shape, (720, 960, 3))
            self.assertFalse(np.array_equal(base, result), axis)
        zoomed = worker.project_x5(panorama, settings.projection_filter(
            {"yaw": 0, "pitch": 0, "roll": 0, "zoom": 1.3}))
        self.assertEqual(zoomed.shape, base.shape)
        self.assertFalse(np.array_equal(base, zoomed))

    def test_worker_applies_to_preview_and_inference_and_rolls_back_failed_save(self):
        pair = worker.CameraPair("molmoact2")
        pair.cameras = {"cam0": object(), "cam1": object()}
        raw = {"cam0": np.full((720, 1280, 3), 32, np.uint8),
               "cam1": np.full((1440, 2880, 3), 32, np.uint8)}
        view = {"yaw": -30, "pitch": 25, "roll": -10, "zoom": 1.3}
        with patch.object(pair, "read_raw", return_value=raw), \
             patch.object(worker, "project_x5", return_value=np.full((720, 960, 3), 42, np.uint8)) as project:
            result = pair.set_insta360_view(view)
            self.assertEqual({key: result["insta360View"][key] for key in view}, view)
            self.assertEqual(settings.load_view(), view)
            pair.read_views()  # Inference uses the same filter as preview.
            self.assertTrue(all(call.args[1] == settings.projection_filter(view) for call in project.call_args_list))
            with patch.object(worker, "save_view", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    pair.set_insta360_view(settings.DEFAULT_VIEW)
            self.assertEqual(pair.profile["x5_view"], view)
            self.assertEqual(settings.load_view(), view)
        pair.failed_roles.add("cam1")
        self.assertIsNone(pair.insta360_view())
        with self.assertRaises(RuntimeError):
            pair.set_insta360_view(view)

    def test_unused_or_fallback_camera_never_exposes_controls(self):
        for model in ["conversation", "molmoact2"]:
            pair = worker.CameraPair(model)
            pair.cameras = {"cam0": object()}
            self.assertIsNone(pair.insta360_view())
            with self.assertRaises(RuntimeError):
                pair.set_insta360_view(settings.DEFAULT_VIEW)
        self.assertFalse(self.path.exists())

    def test_session_rejects_physical_lease_without_sending_worker_command(self):
        session = LiveCameraSession()
        lease_path = Path(self.directory.name) / "lease"
        with lease_path.open("a+b") as lease, patch.object(stream, "LEASE_PATH", lease_path), \
             patch.object(session, "_call") as call:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(stream.PhysicalCameraLeaseBusy):
                session.set_insta360_view("molmoact2", settings.DEFAULT_VIEW)
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
