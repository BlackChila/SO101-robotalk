import sys
import unittest
import io
import json
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from flux3_joint_frame import NAMES
from flux3_start_pose import plan_reset, FluxStartController
from demo_intro_capture import hold_follower


class ResetPlanTest(unittest.TestCase):
    def setUp(self):
        self.start = dict.fromkeys(NAMES, 0.0)
        self.bounds = {name: (-100.0, 100.0) for name in NAMES}
        self.bounds["gripper"] = (0.0, 100.0)

    def test_reset_plan_is_bounded_and_ends_at_saved_pose(self):
        target = {**self.start, "elbow_flex": 18.0, "shoulder_lift": -10.0}
        plan = plan_reset(self.start, target, self.bounds)
        self.assertEqual(plan[-1], target)
        self.assertTrue(all(0 <= action["elbow_flex"] <= 18 for action in plan))
        self.assertLessEqual(max(abs(b["elbow_flex"] - a["elbow_flex"])
                                 for a, b in zip([self.start, *plan[:-1]], plan)), 0.400001)

    def test_rejects_only_out_of_range_reset(self):
        with self.assertRaises(ValueError):
            plan_reset(self.start, {**self.start, "gripper": -0.1}, self.bounds)
        target = {**self.start, "elbow_flex": 90.0}
        self.assertEqual(plan_reset(self.start, target, self.bounds)[-1], target)

    def test_measured_overshoot_is_saturated_before_reset_commands(self):
        start = {**self.start, "elbow_flex": 103.0}
        target = {**self.start, "elbow_flex": 90.0}
        plan = plan_reset(start, target, self.bounds)
        self.assertLessEqual(plan[0]["elbow_flex"], self.bounds["elbow_flex"][1])
        self.assertEqual(plan[-1], target)

    def test_explicit_large_travel_keeps_calibration_and_rate_limits(self):
        target = {**self.start, "shoulder_lift": -90.0, "elbow_flex": 45.0,
                  "gripper": 12.0}
        plan = plan_reset(self.start, target, self.bounds, allow_large_travel=True)
        self.assertEqual(plan[-1], target)
        self.assertTrue(all(self.bounds[n][0] <= action[n] <= self.bounds[n][1]
                            for action in plan for n in NAMES))
        for before, after in zip([self.start, *plan[:-1]], plan):
            self.assertTrue(all(abs(after[n] - before[n]) <=
                                (0.500001 if n == "gripper" else 0.400001)
                                for n in NAMES))

    def test_conversation_multiplier_halves_duration_with_bounded_steps(self):
        target = {**self.start, "shoulder_lift": -80.0, "gripper": 10.0}
        normal = plan_reset(self.start, target, self.bounds)
        faster = plan_reset(self.start, target, self.bounds, speed_multiplier=4.0)
        self.assertEqual(len(faster) * 2, len(normal))
        self.assertEqual(faster[-1], target)
        for before, after in zip([self.start, *faster[:-1]], faster):
            self.assertTrue(all(abs(after[n] - before[n]) <=
                                (1.000001 if n == "gripper" else 0.800001)
                                for n in NAMES))
        with self.assertRaises(ValueError):
            plan_reset(self.start, target, self.bounds, speed_multiplier=4.1)

    def test_subsecond_temperature_spikes_are_logged_without_abort(self):
        controller = FluxStartController.__new__(FluxStartController)
        controller.temperature_spikes = []
        hot = {**self.start, "wrist_roll": 81}
        normal = {**self.start, "wrist_roll": 32}
        temperatures = iter([hot, hot, normal, hot, normal])
        controller.read = lambda register, normalized=False: (
            next(temperatures) if register == "Present_Temperature" else
            dict.fromkeys(NAMES, 1 if register == "Torque_Enable" else 0))
        with patch("flux3_start_pose.time.sleep"):
            controller.health(expect_torque=1)
            controller.health(expect_torque=1)
        self.assertEqual(len(controller.temperature_spikes), 2)

    def test_temperature_must_stay_high_for_one_second_to_abort(self):
        controller = FluxStartController.__new__(FluxStartController)
        controller.temperature_spikes = []
        hot = {**self.start, "wrist_roll": 81}
        clock = [0.0]
        temperatures = [0]
        controller.read = lambda register, normalized=False: (
            (temperatures.__setitem__(0, temperatures[0] + 1) or hot)
            if register == "Present_Temperature" else
            dict.fromkeys(NAMES, 1 if register == "Torque_Enable" else 0))
        def advance(seconds):
            clock[0] += seconds
        with patch("flux3_start_pose.time.sleep", side_effect=advance), \
             patch("flux3_start_pose.time.monotonic", side_effect=lambda: clock[0]), \
             self.assertRaisesRegex(RuntimeError, "at least 1 s"):
            controller.health(expect_torque=1)
        self.assertGreaterEqual(clock[0], 1.0)
        self.assertGreaterEqual(temperatures[0], 20)

    def test_sustained_temperature_logs_each_reading_and_peak(self):
        controller = FluxStartController.__new__(FluxStartController)
        controller.temperature_spikes = []
        clock = [0.0]
        readings = [45, 46, 48]
        def read(register, normalized=False):
            if register == "Present_Temperature":
                value = readings.pop(0) if readings else 45
                return {**self.start, "gripper": value}
            return dict.fromkeys(NAMES, 1 if register == "Torque_Enable" else 0)
        controller.read = read
        output = io.StringIO()
        with (patch("flux3_start_pose.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)),
              patch("flux3_start_pose.time.monotonic", side_effect=lambda: clock[0]),
              patch("sys.stdout", output),
              self.assertRaisesRegex(RuntimeError, "peak_c={'gripper': 48}")):
            controller.health(expect_torque=1)
        samples = [json.loads(line.removeprefix("MOTOR_TEMPERATURE_SAMPLE "))
                   for line in output.getvalue().splitlines()
                   if line.startswith("MOTOR_TEMPERATURE_SAMPLE ")]
        events = [json.loads(line.removeprefix("MOTOR_TEMPERATURE_EVENT "))
                  for line in output.getvalue().splitlines()
                  if line.startswith("MOTOR_TEMPERATURE_EVENT ")]
        self.assertGreaterEqual(len(samples), 20)
        self.assertEqual([sample["temperatures_c"]["gripper"] for sample in samples[:3]],
                         [45, 46, 48])
        self.assertGreaterEqual(samples[-1]["elapsed_seconds"], 1.0)
        self.assertEqual(events[-1]["peak_c"], {"gripper": 48})
        self.assertEqual(events[-1]["sample_count"], len(samples))

    def test_conversation_limit_allows_45_but_stops_sustained_60(self):
        controller = FluxStartController.__new__(FluxStartController)
        controller.temperature_limit_c = 60
        controller.temperature_spikes = []
        clock = [0.0]
        temperature = [45]
        controller.read = lambda register, normalized=False: (
            {**self.start, "gripper": temperature[0]} if register == "Present_Temperature"
            else dict.fromkeys(NAMES, 1 if register == "Torque_Enable" else 0))
        controller.health(expect_torque=1)
        temperature[0] = 60
        with (patch("flux3_start_pose.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)),
              patch("flux3_start_pose.time.monotonic", side_effect=lambda: clock[0]),
              patch("sys.stdout", io.StringIO()),
              self.assertRaisesRegex(RuntimeError, ">=60 C")):
            controller.health(expect_torque=1)

    def test_measured_hold_checks_torque_and_status_without_temperature_abort(self):
        measured = self.start.copy()
        controller = Mock()
        controller.read.side_effect = lambda register: measured
        self.assertEqual(hold_follower(controller), measured)
        controller.robot.bus.sync_write.assert_called_once_with("Goal_Position", measured)
        controller.health.assert_called_once_with(expect_torque=1, check_temperature=False)

        controller = FluxStartController.__new__(FluxStartController)
        controller.temperature_limit_c = 60
        status = [0]
        controller.read = lambda register, normalized=False: (
            {**self.start, "gripper": 60} if register == "Present_Temperature" else
            {**self.start, "gripper": status[0]} if register == "Status" else
            dict.fromkeys(NAMES, 1 if register == "Torque_Enable" else 0))
        controller.health(expect_torque=1, check_temperature=False)
        status[0] = 32
        with self.assertRaisesRegex(RuntimeError, "Motor health"):
            controller.health(expect_torque=1, check_temperature=False)


if __name__ == "__main__":
    unittest.main()
