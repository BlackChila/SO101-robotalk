"""Safety gates for a browser-initiated physical reset (no hardware access)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from flux3_joint_frame import NAMES  # noqa: E402
import flux3_ui_reset  # noqa: E402


class UiResetSafetyTests(unittest.TestCase):
    def test_validated_route_accepts_any_calibrated_start(self) -> None:
        flux3_ui_reset.require_commissioned({"automatic_travel_validated": True})
        measured = dict.fromkeys(NAMES, 0.0)
        measured["shoulder_lift"] = -80.0
        bounds = {name: (-100.0, 100.0) for name in NAMES}
        flux3_ui_reset.assert_measured_in_bounds(measured, bounds)
        measured["shoulder_lift"] = -101.0
        with self.assertRaisesRegex(RuntimeError, "außerhalb der Kalibrierung"):
            flux3_ui_reset.assert_measured_in_bounds(measured, bounds)

    def test_uncommissioned_reset_never_connects_to_robot(self) -> None:
        fake_controller = Mock()
        fake_controller.saved = {"automatic_travel_validated": False}
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(flux3_ui_reset, "FluxStartController", return_value=fake_controller) as factory:
            report_path = Path(temp_dir) / "report.json"
            self.assertEqual(flux3_ui_reset.run(report_path), 1)
            report = json.loads(report_path.read_text())
        self.assertEqual(factory.call_count, 1)
        fake_controller.connect.assert_not_called()
        self.assertEqual(report["outcome"], "aborted")
        self.assertIn("nicht validiert", report["error"])

    def test_tracking_fault_stops_before_next_goal(self) -> None:
        goal = dict.fromkeys(NAMES, 0.0)
        flux3_ui_reset.assert_tracking(goal, dict(goal, elbow_flex=2.0))
        actual = dict(goal, elbow_flex=15.1)
        with self.assertRaisesRegex(RuntimeError, "Nachführfehler elbow_flex"):
            flux3_ui_reset.assert_tracking(goal, actual)

    def test_lagging_goal_is_limited_and_final_pose_uses_proven_tolerance(self) -> None:
        actual = dict.fromkeys(NAMES, 0.0)
        target = dict(actual, elbow_flex=20.0)
        self.assertEqual(flux3_ui_reset.bounded_goal(target, actual)["elbow_flex"], 10.0)
        self.assertTrue(flux3_ui_reset.at_start_pose(
            dict(actual, elbow_flex=16.1), target))
        self.assertFalse(flux3_ui_reset.at_start_pose(
            dict(actual, elbow_flex=15.9), target))

    def test_hold_releases_on_explicit_r(self) -> None:
        controller = Mock()
        controller.target = dict.fromkeys(NAMES, 0.0)
        controller.read.return_value = controller.target
        with patch.object(flux3_ui_reset.select, "select", return_value=([object()], [], [])), \
             patch.object(flux3_ui_reset.sys, "stdin", Mock(readline=Mock(return_value="r\n"))):
            self.assertEqual(flux3_ui_reset.hold_until_release(controller), "operator_release")
        controller.health.assert_called_with(expect_torque=1)

    def test_tracking_fault_aborts_reset_and_runs_torque_cleanup(self) -> None:
        start = dict.fromkeys(NAMES, 0.0)
        first = dict(start, elbow_flex=2.0)
        second = dict(start, elbow_flex=3.0)
        controller = Mock()
        controller.saved = {"automatic_travel_validated": True}
        controller.target = second
        controller.bounds = {name: (-100.0, 100.0) for name in NAMES}
        controller.bounds["gripper"] = (0.0, 100.0)
        controller.inspect_plan.return_value = (start, [first, second])
        current_goal = start

        def write(register, goal):
            nonlocal current_goal
            current_goal = goal

        controller.robot.bus.sync_write.side_effect = write
        controller.read.side_effect = lambda register: (
            current_goal if register == "Goal_Position" else
            (dict(start, elbow_flex=20.0) if current_goal["elbow_flex"] else start)
        )
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(flux3_ui_reset, "FluxStartController", return_value=controller), \
             patch.object(flux3_ui_reset.time, "sleep"):
            report = Path(temp_dir) / "report.json"
            self.assertEqual(flux3_ui_reset.run(report), 1)
            saved = json.loads(report.read_text())
        self.assertIn("Nachführfehler elbow_flex", saved["error"])
        self.assertEqual(controller.robot.bus.sync_write.call_count, 2)
        controller.close.assert_called_once()

    def test_stalled_servo_aborts_with_bounded_goal(self) -> None:
        start = dict.fromkeys(NAMES, 0.0)
        target = dict(start, elbow_flex=18.0)
        controller = Mock()
        controller.saved = {"automatic_travel_validated": True}
        controller.target = target
        controller.bounds = {name: (-100.0, 100.0) for name in NAMES}
        controller.inspect_plan.return_value = (start, [target])
        current_goal = start
        clock = [0.0]

        def write(register, goal):
            nonlocal current_goal
            current_goal = goal

        controller.robot.bus.sync_write.side_effect = write
        controller.read.side_effect = lambda register: (
            current_goal if register == "Goal_Position" else start)
        with patch.object(flux3_ui_reset.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(flux3_ui_reset.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
             self.assertRaisesRegex(RuntimeError, "Keine gemessene Bewegung"):
            flux3_ui_reset.move_monitored(controller, [])
        sent = [call.args[1]["elbow_flex"]
                for call in controller.robot.bus.sync_write.call_args_list]
        self.assertLessEqual(max(sent), 10.0)

    def test_return_from_held_pose_does_not_toggle_torque(self) -> None:
        start = dict.fromkeys(NAMES, 0.0)
        controller = Mock()
        controller.target = start
        controller.bounds = {name: (-100.0, 100.0) for name in NAMES}
        controller.inspect_plan.return_value = (start, [])
        controller.read.return_value = start
        result = flux3_ui_reset.move_monitored(controller, [], already_holding=True)
        self.assertEqual(result, start)
        controller.robot.bus.sync_write.assert_called_once_with("Goal_Position", start)
        controller.robot.bus.enable_torque.assert_not_called()
        controller.health.assert_called_with(expect_torque=1)


if __name__ == "__main__":
    unittest.main()
