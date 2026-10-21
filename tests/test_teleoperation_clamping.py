"""Exercise the UI teleoperation runner with fake buses, never real hardware."""

import io
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import leader_teleoperate as teleop
from demo_intro_capture import checked_action
from flux3_start_pose import calibrated_bounds


class TeleoperationClampingTests(unittest.TestCase):
    def setUp(self):
        # Preserve the reported wrist boundary without depending on local hardware files.
        self.bounds = calibrated_bounds({name: {"range_min": 902, "range_max": 3226}
                                         for name in teleop.NAMES})

    @staticmethod
    def action(wrist=0.0, **overrides):
        result = {f"{name}.pos": 0.0 for name in teleop.NAMES}
        result["wrist_flex.pos"] = wrist
        result.update(overrides)
        return result

    def test_endpoint_saturation_and_return_have_no_offset(self):
        high = self.bounds["wrist_flex"][1]
        for requested, expected in ((103.03296703296704, high), (109.8, high),
                                    (105, high), (100, 100), (-109.8, -high), (-90, -90)):
            with self.subTest(requested=requested):
                action = self.action(requested, **{"elbow_flex.pos": 12.5})
                target, limited = teleop.clamp_leader_action(action, self.bounds)
                self.assertEqual(target["wrist_flex"], expected)
                self.assertEqual(target["elbow_flex"], 12.5)
                self.assertEqual(limited, ["wrist_flex"] if requested != expected else [])
                self.assertEqual(action["wrist_flex.pos"], requested)

    def test_gripper_is_bounded_in_its_own_units(self):
        for requested, expected in ((-4, 0), (104, 100), (53, 53)):
            target, _ = teleop.clamp_leader_action(
                self.action(**{"gripper.pos": requested}), self.bounds)
            self.assertEqual(target["gripper"], expected)

    def test_invalid_readings_still_fail(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(RuntimeError, "Nonfinite"):
                teleop.clamp_leader_action(self.action(value), self.bounds)
        with self.assertRaisesRegex(RuntimeError, "Incomplete"):
            teleop.clamp_leader_action({"wrist_flex.pos": 0}, self.bounds)

    def test_shared_capture_checker_still_rejects_outside_calibration(self):
        with self.assertRaisesRegex(RuntimeError, "outside follower calibration"):
            checked_action(SimpleNamespace(bounds=self.bounds), self.action(103.03296703296704))

    def run_fake_session(self, start_wrist, measured_wrist, live_actions,
                         *, follows=True, read_delay=0.0, health_fault=False):
        measured = {name: 0.0 for name in teleop.NAMES}
        measured["wrist_flex"] = measured_wrist
        goal = dict(measured)
        writes = []
        clock = [0.0]
        sleeps = []
        bus = MagicMock(is_connected=True, is_calibrated=True)
        controller = SimpleNamespace(robot=SimpleNamespace(bus=bus), armed=False,
                                     bounds=self.bounds)

        def write(register, values):
            self.assertEqual(register, "Goal_Position")
            writes.append(dict(values))
            goal.update(values)
            if follows:
                measured.update(values)

        def read(register, **kwargs):
            if register == "Present_Position":
                return dict(measured)
            if register == "Goal_Position":
                return dict(goal)
            if register == "Torque_Enable":
                return {name: int(controller.armed) for name in teleop.NAMES}
            raise AssertionError(register)

        bus.sync_write.side_effect = write
        controller.read = read
        # Fail at the first periodic health check, after preflight and initial hold.
        controller.health = MagicMock(side_effect=[None, None, RuntimeError("Motor health fault"), None]
                                      if health_fault else None)
        actions = iter([self.action(start_wrist), *live_actions])

        def get_action():
            clock[0] += read_delay
            return next(actions)

        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        leader = SimpleNamespace(bus=MagicMock(is_connected=True), is_calibrated=True,
                                 get_action=MagicMock(side_effect=get_action))
        leader.bus.sync_read.return_value = {name: 0 for name in teleop.NAMES}
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            with patch.object(teleop, "FluxStartController", return_value=controller), \
                 patch.object(teleop, "create_leader", return_value=leader), \
                 patch.object(teleop.fcntl, "ioctl"), \
                 patch.object(teleop.time, "sleep", side_effect=sleep), \
                 patch.object(teleop.time, "monotonic", side_effect=lambda: clock[0]), \
                 patch.object(teleop.select, "select", side_effect=[
                     *[([], [], []) for _ in live_actions], ([sys.stdin], [], [])]), \
                 patch.object(sys, "stdin", io.StringIO("q\n")), \
                 patch.object(sys, "argv", ["teleop", "--report", str(report_path)]), \
                 redirect_stdout(io.StringIO()):
                result = teleop.main()
            report = json.loads(report_path.read_text())
        bus.disconnect.assert_called_once_with(disable_torque=False)
        self.assertTrue(report["hold_verified"])
        self.assertTrue(controller.armed)
        self.assertEqual(writes[-1], measured)
        self.assertTrue(all(seconds >= 0 for seconds in sleeps))
        return result, report, writes

    def test_live_loop_saturates_then_resumes_and_stops_holding(self):
        result, report, writes = self.run_fake_session(
            0, 0, [self.action(103.03296703296704), self.action(109.8), self.action(90)])
        self.assertEqual(result, 0)
        self.assertEqual(report["state"], "stopped")
        self.assertEqual(report["limited_joints"], [])
        self.assertEqual([v["wrist_flex"] for v in writes[-4:]],
                         [self.bounds["wrist_flex"][1], self.bounds["wrist_flex"][1], 90, 90])

    def test_startup_alignment_uses_bounded_target(self):
        result, report, writes = self.run_fake_session(109.8, 95, [])
        self.assertEqual(result, 0)
        self.assertEqual(report["limited_joints"], ["wrist_flex"])
        self.assertIsNone(report["message"])
        self.assertTrue(all(v["wrist_flex"] <= self.bounds["wrist_flex"][1] for v in writes))
        self.assertEqual(writes[-1]["wrist_flex"], self.bounds["wrist_flex"][1])

    def test_invalid_live_reading_aborts_with_verified_hold(self):
        result, report, _ = self.run_fake_session(0, 0, [self.action(math.nan)])
        self.assertEqual(result, 1)
        self.assertEqual(report["state"], "failed")
        self.assertIn("Nonfinite", report["error"])

    def test_fast_leader_and_large_tracking_lag_do_not_abort(self):
        # Follower remains at zero while the Leader makes large, rapid reversals.
        values = [90, -90, 100, -100, 109.8, -109.8] * 10
        result, report, writes = self.run_fake_session(
            0, 0, [self.action(v) for v in values], follows=False)
        self.assertEqual(result, 0)
        self.assertEqual(report["state"], "stopped")
        self.assertIsNone(report["error"])
        high = self.bounds["wrist_flex"][1]
        self.assertEqual([v["wrist_flex"] for v in writes[2:-1]],
                         [max(-high, min(high, v)) for v in values])
        # Stop holds the actual pose rather than chasing the last Leader target.
        self.assertEqual(writes[-1]["wrist_flex"], 0)

    def test_delayed_reads_continue_with_one_command_per_fresh_sample(self):
        values = [90, -90, 80, -80] * 10
        result, report, writes = self.run_fake_session(
            0, 0, [self.action(v) for v in values], follows=False, read_delay=0.3)
        self.assertEqual(result, 0)
        self.assertEqual(report["state"], "stopped")
        self.assertEqual([v["wrist_flex"] for v in writes[2:-1]], values)

    def test_late_tick_rebases_schedule_without_catch_up_burst(self):
        with patch.object(teleop.time, "monotonic", side_effect=[10.3, 10.305]), \
             patch.object(teleop.time, "sleep") as sleep:
            next_tick = teleop.pace_teleoperation(10.0, 0.02)
            self.assertEqual(next_tick, 10.3)
            sleep.assert_not_called()
            next_tick = teleop.pace_teleoperation(next_tick, 0.02)
            self.assertAlmostEqual(next_tick, 10.32)
            self.assertAlmostEqual(sleep.call_args.args[0], 0.015)

    def test_motor_fault_still_aborts_with_verified_hold(self):
        result, report, writes = self.run_fake_session(
            0, 0, [self.action(90)] * 30, follows=False, health_fault=True)
        self.assertEqual(result, 1)
        self.assertEqual(report["state"], "failed")
        self.assertIn("Motor health fault", report["error"])
        self.assertEqual(writes[-1]["wrist_flex"], 0)


if __name__ == "__main__":
    unittest.main()
