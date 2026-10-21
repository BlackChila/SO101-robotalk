"""The FLUX-only bridge follows LeRobot's published pre-#777 conversion."""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from flux3_joint_frame import NAMES, current_to_legacy, floor_gripper_at_zero, legacy_to_current


class JointFrameTest(unittest.TestCase):
    def test_published_pr777_action_mapping_and_delta_direction(self) -> None:
        # LeRobot's migration says shoulder_new = -(shoulder_old - 90)
        # and elbow_new = elbow_old - 90. Check fixed external examples,
        # because a round trip alone also passes for a consistently wrong map.
        old = dict.fromkeys(NAMES, 0.0)
        old["shoulder_lift"] = 180.0
        old["elbow_flex"] = 90.0
        current = legacy_to_current(old)
        self.assertEqual(current["shoulder_lift"], -90.0)
        self.assertEqual(current["elbow_flex"], 0.0)
        old["shoulder_lift"] += 4.0
        old["elbow_flex"] += 4.0
        next_current = legacy_to_current(old)
        self.assertEqual(next_current["shoulder_lift"] - current["shoulder_lift"], -4.0)
        self.assertEqual(next_current["elbow_flex"] - current["elbow_flex"], 4.0)

    def test_explicit_flux_gripper_floor_only_changes_negative_gripper(self):
        action = dict.fromkeys(NAMES, 1.25)
        action["gripper"] = -0.21
        corrected = floor_gripper_at_zero(action)
        self.assertEqual(corrected["gripper"], 0.0)
        self.assertEqual(corrected["shoulder_lift"], 1.25)
        self.assertEqual(action["gripper"], -0.21)
        for value in (0.0, 12.0, 101.0):
            action["gripper"] = value
            self.assertEqual(floor_gripper_at_zero(action)["gripper"], value)

    def test_round_trip_with_measured_parked_pose(self) -> None:
        current = dict(zip(NAMES, (-2.33, -111.56, 95.96, 76.13, -2.33, 0.275), strict=True))
        old = current_to_legacy(current)
        self.assertTrue(math.isclose(old["shoulder_lift"], 201.56))
        self.assertTrue(math.isclose(old["elbow_flex"], 185.96))
        for name in NAMES:
            self.assertTrue(math.isclose(legacy_to_current(old)[name], current[name], abs_tol=1e-9))

    def test_reject_incomplete_joint_vectors(self) -> None:
        with self.assertRaises(ValueError):
            current_to_legacy({"shoulder_lift": 0.0})
        with self.assertRaises(ValueError):
            legacy_to_current({"shoulder_lift": 90.0})


if __name__ == "__main__":
    unittest.main()
