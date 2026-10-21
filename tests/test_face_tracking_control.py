"""Offline image-feedback behavior; no camera or physical motor access."""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from face_tracking_control import AXES, FaceTrackingController


class FaceTrackingControlTests(unittest.TestCase):
    def setUp(self):
        self.pose = {"shoulder_pan": 0.0, "wrist_flex": 40.0, "wrist_roll": 0.4}
        self.control = FaceTrackingController({axis: (-90, 90) for axis in AXES})
        self.sequence = 0

    def observation(self, now, **changes):
        self.sequence += 1
        return {"sequence": self.sequence, "captured_at": now,
                "detected": True, "x": 0.99, "y": 0.9, "confidence": 0.95, **changes}

    def test_disabled_and_enabled_without_camera_never_search(self):
        self.assertEqual(self.control.tick(0, self.pose), {})
        self.control.enable(self.pose, 0)
        self.assertEqual(self.control.tick(10, self.pose), {axis: self.pose[axis] for axis in AXES})
        self.assertEqual(self.control.state, "waiting_for_camera")

    def test_positive_errors_increase_both_targets_with_speed_and_acceleration_bounds(self):
        self.control.enable(self.pose, 0)
        previous_speed = {axis: 0 for axis in AXES}
        previous = self.pose.copy()
        for index in range(1, 101):
            now = index * 0.02
            self.control.observe(self.observation(now), now)
            target = self.control.tick(now, previous)
            for axis in AXES:
                speed = (target[axis] - previous[axis]) / 0.02
                self.assertGreater(speed, 0)
                self.assertLessEqual(speed, 10.4 + 1e-9)
                self.assertLessEqual(abs(speed - previous_speed[axis]), 0.52 + 1e-9)
                previous_speed[axis] = speed
            previous.update(target)

    def test_stale_frame_holds_measured_position_and_does_not_search(self):
        self.control.enable(self.pose, 0)
        self.control.observe(self.observation(0.1), 0.1)
        self.assertGreater(self.control.tick(0.1, self.pose)[AXES[0]], self.pose[AXES[0]])
        for now in (1.0, 4.0, 100.0):
            self.assertEqual(self.control.tick(now, self.pose), {axis: self.pose[axis] for axis in AXES})
            self.assertEqual(self.control.state, "camera_stale")

    def test_left_and_up_reduce_angles_and_tracking_stops_at_origin_envelope(self):
        self.control.enable(self.pose, 0)
        actual = self.pose.copy()
        for index in range(1, 2001):
            now = index * 0.02
            self.control.observe(self.observation(now, x=0.0, y=0.0), now)
            actual.update(self.control.tick(now, actual))
            self.assertGreaterEqual(actual[AXES[0]], -90)
            self.assertGreaterEqual(actual[AXES[1]], -30)
        self.assertEqual(actual[AXES[0]], -90)
        self.assertEqual(actual[AXES[1]], -30)

    def test_malformed_duplicate_old_future_and_nonfinite_observations_rejected(self):
        self.control.enable(self.pose, 10)
        good = self.observation(10.1)
        self.assertTrue(self.control.observe(good, 10.1))
        for bad in (good, self.observation(9.9), self.observation(10.2),
                    self.observation(math.nan), self.observation(10.1, x=math.inf),
                    self.observation(10.1, detected="yes"), self.observation(10.1, sequence=True),
                    self.observation(10.1, x=1.1), self.observation(10.1, confidence=-1)):
            self.assertFalse(self.control.observe(bad, 10.1))
        self.assertFalse(self.control.observe(self.observation(10.2), 11))

    def test_low_confidence_does_not_track_and_search_requires_continuous_fresh_frames(self):
        self.control.enable(self.pose, 0)
        for index in range(1, 17):
            now = index * 0.1
            self.assertTrue(self.control.observe(self.observation(now, confidence=0.3), now))
            target = self.control.tick(now, self.pose)
            if now < 1.1:
                self.assertEqual(target[AXES[0]], self.pose[AXES[0]])
        self.assertEqual(self.control.state, "searching")
        self.assertGreater(target[AXES[0]], self.pose[AXES[0]])
        self.assertLess(target[AXES[1]], self.pose[AXES[1]])
        self.control.tick(5, self.pose)
        self.control.observe(self.observation(5.1, detected=False), 5.1)
        self.control.tick(5.1, self.pose)
        self.assertEqual(self.control.state, "face_lost")

    def test_search_can_be_disabled_and_confirmed_target_dead_zone_clears_motion(self):
        self.control.enable(self.pose, 0, search=False)
        for index in range(1, 31):
            now = index * 0.1
            self.control.observe(self.observation(now, detected=False), now)
            self.control.tick(now, self.pose)
        self.assertEqual(self.control.state, "face_lost")
        self.control.observe(self.observation(3.1, x=0.91, y=0.49), 3.1)
        self.assertEqual(self.control.tick(3.1, self.pose), {axis: self.pose[axis] for axis in AXES})

    def test_targets_never_run_ahead_of_measured_position(self):
        self.control.enable(self.pose, 0)
        for index in range(1, 501):
            now = index * 0.02
            self.control.observe(self.observation(now), now)
            goal = self.control.tick(now, self.pose)
            for axis in AXES:
                self.assertLessEqual(goal[axis] - self.pose[axis], 2)

    def test_search_sweeps_both_directions_inside_calibration_and_origin_envelope(self):
        self.pose["shoulder_pan"] = 89
        self.control.enable(self.pose, 0)
        actual = self.pose.copy()
        positions = []
        for index in range(1, 6001):
            now = index * 0.02
            self.control.observe(self.observation(now, detected=False), now)
            actual.update(self.control.tick(now, actual))
            positions.append(actual[AXES[0]])
            self.assertGreaterEqual(actual[AXES[0]], -6)
            self.assertLessEqual(actual[AXES[0]], 90)
        self.assertLess(min(positions), -5)
        self.assertGreater(max(positions), 89.5)

    def test_disable_flushes_capture_and_reenable_rejects_old_generation(self):
        self.control.enable(self.pose, 0)
        observation = self.observation(0.1)
        self.control.observe(observation, 0.1)
        self.control.disable()
        self.assertFalse(self.control.observe(observation, 0.2))
        self.control.enable(self.pose, 0.3)
        self.assertFalse(self.control.observe(observation, 0.3))
        self.assertEqual(self.control.state, "waiting_for_camera")

    def test_search_reaches_sixteen_degrees_per_second_in_selected_direction(self):
        for direction, sign in (("left", -1), ("right", 1)):
            self.control.enable(self.pose, 0, search_direction=direction)
            actual = self.pose.copy()
            for index in range(1, 151):
                now = index * .02
                self.control.observe(self.observation(now, detected=False), now)
                previous = actual.copy()
                actual.update(self.control.tick(now, actual))
            self.assertAlmostEqual((actual["shoulder_pan"] - previous["shoulder_pan"]) / .02, sign * 16)
            self.assertLess(actual["wrist_flex"], self.pose["wrist_flex"])

    def test_selected_direction_reverses_at_calibration_boundary(self):
        for direction, angle, sign in (("left", -90, 1), ("right", 90, -1)):
            pose = {**self.pose, "shoulder_pan": angle}
            self.control.enable(pose, 0, search_direction=direction)
            for index in range(1, 81):
                now = index * .02
                self.control.observe(self.observation(now, detected=False), now)
                target = self.control.tick(now, pose)
            self.assertGreater(sign * (target["shoulder_pan"] - angle), 0)

    def test_top_edge_face_tracks_past_old_wrist_limit_and_reports_new_limit(self):
        self.pose["wrist_flex"] = 71.5
        self.control.enable(self.pose, 0)
        actual = self.pose.copy()
        for index in range(1, 601):
            now = index * .02
            self.control.observe(self.observation(now, x=.90, y=.03), now)
            actual.update(self.control.tick(now, actual))
        self.assertAlmostEqual(actual["wrist_flex"], 1.5)
        self.assertEqual(actual["shoulder_pan"], self.pose["shoulder_pan"])
        self.assertEqual(self.control.status()["limit_reached"], {"wrist_flex": "low"})
        # Moving the face below centre must release the limit and track downward.
        for index in range(601, 651):
            now = index * .02
            self.control.observe(self.observation(now, x=.90, y=.97), now)
            actual.update(self.control.tick(now, actual))
        self.assertGreater(actual["wrist_flex"], 1.5)
        self.assertEqual(self.control.status()["limit_reached"], {})
        self.control.tick(20, actual)
        self.assertEqual(self.control.status()["limit_reached"], {})

    def test_wrist_downward_travel_still_respects_calibration(self):
        for origin, expected_low, expected_high in ((40, -30, 90), (80, 10, 90), (-80, -90, -30)):
            actual = {**self.pose, "wrist_flex": origin}
            self.control.enable(actual, 0)
            self.assertEqual(self.control.limits["wrist_flex"], (expected_low, expected_high))
            for index in range(1, 501):
                now = index * .02
                self.control.observe(self.observation(now, x=.90, y=.97), now)
                actual.update(self.control.tick(now, actual))
            self.assertAlmostEqual(actual["wrist_flex"], expected_high)
            self.assertEqual(self.control.status()["limit_reached"], {"wrist_flex": "high"})

    def test_search_looks_up_before_base_sweep_and_stops_at_seventy_degrees(self):
        self.control.enable(self.pose, 0)
        actual = self.pose.copy()
        for index in range(1, 1001):
            now = index * .02
            previous = actual.copy()
            self.control.observe(self.observation(now, detected=False), now)
            actual.update(self.control.tick(now, actual))
            self.assertLessEqual(abs(actual["wrist_flex"] - previous["wrist_flex"]), .08 + 1e-8)
            if now < .35:
                self.assertEqual(actual["wrist_flex"], 40)
            if .5 < now < 1:
                self.assertLess(actual["wrist_flex"], 40)
                self.assertEqual(actual["shoulder_pan"], 0)
        self.assertAlmostEqual(actual["wrist_flex"], -30, delta=.3)
        self.control.observe(self.observation(20.02, x=.90, y=.9), 20.02)
        before = actual["wrist_flex"]
        for index in range(1001, 1026):
            now = index * .02
            self.control.observe(self.observation(now, x=.90, y=.9), now)
            actual.update(self.control.tick(now, actual))
        self.assertGreater(actual["wrist_flex"], before)
        self.control.tick(22, actual)
        self.assertEqual(self.control.state, "camera_stale")
        self.assertIsNone(self.control.search_wrist_target)

    def test_vertical_tracking_continues_until_face_is_at_half_image_height(self):
        self.control.enable(self.pose, 0)
        actual = self.pose.copy()
        for index in range(1, 301):
            now = index * .02
            y = .2 if index < 201 else .5
            self.control.observe(self.observation(now, x=.90, y=y), now)
            previous = actual.copy()
            actual.update(self.control.tick(now, actual))
        self.assertLess(actual["wrist_flex"], self.pose["wrist_flex"])
        self.assertAlmostEqual(actual["wrist_flex"], previous["wrist_flex"], places=9)
        self.assertEqual(self.control.state, "tracking")

    def test_invalid_search_direction_cannot_enable(self):
        with self.assertRaises(ValueError):
            self.control.enable(self.pose, 0, search_direction="backward")
        self.assertFalse(self.control.enabled)

    def test_rolled_camera_is_blocked_without_any_reorientation(self):
        with self.assertRaisesRegex(ValueError, "natural wrist roll"):
            self.control.enable({**self.pose, "wrist_roll": 82.9}, 0)
        self.assertFalse(self.control.enabled)


if __name__ == "__main__":
    unittest.main()
