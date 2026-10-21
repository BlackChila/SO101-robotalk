"""Offline geometry regression checks; no camera or robot connections."""
import sys
import os
from unittest.mock import patch
import threading
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from camera_profiles import camera_profile, center_crop_box, crop_4x3


class CameraProfileTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SO101_CAMERA_GEOMETRY": "highres_4x3"})
        env.start()
        self.addCleanup(env.stop)


    def test_molmo_camera_2_is_x5_with_own_processor_resize(self):
        profile = camera_profile("molmoact2")
        self.assertIn("Insta360_X5", profile["cameras"]["cam1"]["path"])
        self.assertEqual(profile["slots"], {"cam0": "observation.images.cam0",
                                            "cam1": "observation.images.cam1"})
        self.assertEqual(profile["model_view_hw"], [378, 378])
        self.assertEqual(profile["resize_owner"], "molmo_processor")

    def test_conversation_wrist_observers_capture_native_frame_and_crop_preview(self):
        for model_id in ("conversation", "molmoact2"):
            wrist = camera_profile(model_id)["observer_cameras"]["wrist"]
            self.assertEqual((wrist["width"], wrist["height"]), (1920, 1080))
            self.assertEqual(wrist["crop"], [240, 0, 1440, 1080])
        self.assertEqual(camera_profile("conversation")["geometry"],
                         "independent_4x3")
        # Policy inputs retain their existing geometry.
        self.assertEqual(camera_profile("molmoact2")["cameras"]["cam0"]["crop"],
                         [160, 0, 960, 720])


    def test_maximum_crop_preserves_exact_pixels(self):
        for w, h, box in [(1280, 720, (160, 0, 960, 720)),
                          (1920, 1080, (240, 0, 1440, 1080))]:
            raw = np.random.default_rng(42).integers(0, 256, (h, w, 3), dtype=np.uint8)
            self.assertEqual(center_crop_box(w, h), box)
            cropped = crop_4x3(raw)
            x, y, cw, ch = box
            np.testing.assert_array_equal(cropped, raw[y:y+ch, x:x+cw])
            self.assertTrue(np.shares_memory(raw, cropped))
            np.testing.assert_array_equal(crop_4x3(cropped), cropped)

    def test_invalid_mode_or_crop_rejected(self):
        raw = np.zeros((720, 1280, 3), np.uint8)
        for crop in [(-1, 0, 960, 720), (0, 0, 1280, 720), (400, 0, 960, 720)]:
            with self.assertRaises(ValueError):
                crop_4x3(raw, crop)
        with self.assertRaises(ValueError):
            crop_4x3(raw, expected_wh=(640, 480))

    def test_profiles_do_not_share_mutable_configuration(self):
        first = camera_profile("molmoact2")
        first["cameras"]["cam0"]["crop"][0] = 0
        self.assertEqual(camera_profile("molmoact2")["cameras"]["cam0"]["crop"][0], 160)






if __name__ == "__main__":
    torch.set_num_threads(2)
    unittest.main()
