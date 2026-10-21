"""Offline checks for explicit SO-101 torque hold and verified release."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import flux3_ui_torque as torque  # noqa: E402


class TorqueRunnerTests(unittest.TestCase):
    def test_enable_uses_measured_pose_as_only_goal(self) -> None:
        names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
        measured = {name: 1.0 for name in names}
        controller = SimpleNamespace(
            connect=Mock(), read=Mock(return_value=measured),
            bounds={name: (0.0, 100.0) for name in names},
            robot=SimpleNamespace(bus=SimpleNamespace(sync_write=Mock(), enable_torque=Mock())),
            health=Mock(), armed=False,
        )
        with patch.object(torque, "assert_goal_echo") as echo:
            result = torque.enable_hold(controller)
        self.assertEqual(result, measured)
        controller.robot.bus.sync_write.assert_called_once_with("Goal_Position", measured)
        echo.assert_called_once_with(controller, measured)
        controller.robot.bus.enable_torque.assert_called_once_with(num_retry=1)
        controller.health.assert_called_once_with(expect_torque=1)

    def test_off_disables_enabled_motors_and_checks_readback(self) -> None:
        before = {"motor": 1}
        after = {"motor": 0}
        bus = SimpleNamespace(
            connect=Mock(), disconnect=Mock(), disable_torque=Mock(), is_calibrated=True,
            port_handler=SimpleNamespace(ser=SimpleNamespace(fileno=Mock(return_value=12))),
        )
        controller = SimpleNamespace(robot=SimpleNamespace(bus=bus), read=Mock(side_effect=[before, after]), armed=False)
        with patch.object(torque.fcntl, "ioctl"):
            result = torque.turn_off_once(controller)
        self.assertEqual(result, {"before": before, "after": after})
        bus.disable_torque.assert_called_once_with(num_retry=3)
        bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_off_rejects_failed_readback(self) -> None:
        bus = SimpleNamespace(
            connect=Mock(), disconnect=Mock(), disable_torque=Mock(), is_calibrated=True,
            port_handler=SimpleNamespace(ser=SimpleNamespace(fileno=Mock(return_value=12))),
        )
        controller = SimpleNamespace(robot=SimpleNamespace(bus=bus),
                                     read=Mock(side_effect=[{"motor": 1}, {"motor": 1}]), armed=False)
        with patch.object(torque.fcntl, "ioctl"):
            with self.assertRaisesRegex(RuntimeError, "readback failed"):
                torque.turn_off_once(controller)
        bus.disconnect.assert_called_once_with(disable_torque=False)


if __name__ == "__main__":
    unittest.main()
