import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from flux3_scene_setup import (
    _control_argument, _validated_crop, equirectangular_to_perspective,
    exposure_ok, luminance_metrics,
)


class SceneSetupTest(unittest.TestCase):
    def test_crop_has_exact_requested_shape(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        crop = _validated_crop(frame, (20, 10, 80, 40))
        self.assertEqual(crop.shape, (40, 80, 3))

    def test_out_of_frame_crop_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not fit"):
            _validated_crop(np.zeros((100, 200, 3), dtype=np.uint8), (150, 10, 80, 40))

    def test_luminance_check_rejects_black_and_clipped_frames(self):
        black = luminance_metrics(np.zeros((20, 20, 3), dtype=np.uint8))
        white = luminance_metrics(np.full((20, 20, 3), 255, dtype=np.uint8))
        self.assertFalse(exposure_ok("overhead", black))
        self.assertFalse(exposure_ok("overhead", white))

    def test_luminance_check_accepts_visible_midtones(self):
        frame = np.full((20, 20, 3), 90, dtype=np.uint8)
        self.assertTrue(exposure_ok("overhead", luminance_metrics(frame)))

    def test_controls_are_formatted_for_v4l2_ctl(self):
        self.assertEqual(_control_argument({"gain": 30, "gamma": 150}), "gain=30,gamma=150")

    def test_equirectangular_projection_has_requested_shape(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        projected = equirectangular_to_perspective(
            frame, yaw_deg=0, pitch_deg=-30, horizontal_fov_deg=70, width=64, height=48)
        self.assertEqual(projected.shape, (48, 64, 3))


if __name__ == "__main__":
    unittest.main()
