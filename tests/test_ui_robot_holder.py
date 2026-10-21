"""No-device checks for the UI's exclusive serial action executor."""

import sys
import tempfile
import unittest
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ui_robot_holder as holder  # noqa: E402


NAMES = holder.NAMES


def pose(value=0.0):
    return dict.fromkeys(NAMES, float(value))


class HolderTests(unittest.TestCase):
    def test_snapshot_pairs_live_camera_frame_with_measured_state(self):
        class Cameras:
            def __init__(self, model_id):
                self.model_id = model_id

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def fresh(self, **_):
                return {"scene": np.zeros((2, 3, 3), np.uint8),
                        "wrist": np.ones((2, 3, 3), np.uint8)}, {}

        controller = self.controller()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "outputs"
            output.mkdir()
            path = output / "ui-robot-observation-test.npz"
            with (patch.object(holder, "ROOT", root),
                  patch.object(holder, "SharedCameraClient", Cameras)):
                result = holder.snapshot(controller, "molmoact2", path)
            with np.load(path, allow_pickle=False) as saved:
                self.assertEqual(set(saved.files), {"scene", "wrist"})
                self.assertEqual(saved["scene"].shape, (1, 2, 3, 3))
            self.assertEqual(result["status"], "observed")
            self.assertEqual(result["state"], pose())

    def controller(self):
        bus = SimpleNamespace(sync_write=Mock(), read=Mock(return_value=300), write=Mock())
        return SimpleNamespace(
            bounds={name: (-100.0, 100.0) for name in NAMES},
            robot=SimpleNamespace(bus=bus),
            read=Mock(side_effect=lambda register: pose()),
            health=Mock(),
        )

    def test_molmo_gripper_limit_is_written_and_verified_before_goal(self):
        controller = self.controller()
        controller.robot.bus.read.side_effect = [1000, 300]
        with (patch.object(holder, "assert_goal_echo"),
              patch.object(holder.select, "select", return_value=([], [], [])),
              patch.object(holder.time, "sleep")):
            holder.execute_actions(controller, "molmoact2", pose(), [pose()])
        controller.robot.bus.write.assert_called_once_with(
            "Torque_Limit", "gripper", 300, normalize=False, num_retry=2)
        controller.robot.bus.sync_write.assert_called()

    def test_unverified_molmo_gripper_limit_blocks_motor_goals(self):
        controller = self.controller()
        controller.robot.bus.read.side_effect = [1000, 1000]
        with self.assertRaisesRegex(RuntimeError, "torque limit unverified"):
            holder.execute_actions(controller, "molmoact2", pose(), [pose()])
        controller.robot.bus.sync_write.assert_not_called()

    def test_rejects_out_of_bounds_block_before_any_motor_write(self):
        controller = self.controller()
        bad = pose()
        bad["shoulder_pan"] = 101.0
        with self.assertRaisesRegex(RuntimeError, "outside calibration"):
            holder.execute_actions(controller, "molmoact2", pose(), [bad])
        controller.robot.bus.sync_write.assert_not_called()

    def test_rejects_large_jump_between_policy_actions_before_any_motor_write(self):
        controller = self.controller()
        bad = pose()
        bad["shoulder_pan"] = 26.0
        with self.assertRaisesRegex(RuntimeError, "25-unit step"):
            holder.execute_actions(controller, "molmoact2", pose(), [pose(), bad])
        controller.robot.bus.sync_write.assert_not_called()

    def test_first_policy_target_is_limited_from_current_pose_without_abort(self):
        controller = self.controller()
        far = pose()
        far["gripper"] = 30.0
        with (patch.object(holder, "assert_goal_echo"),
              patch.object(holder.select, "select", return_value=([], [], [])),
              patch.object(holder.time, "sleep")):
            result = holder.execute_actions(controller, "molmoact2", pose(), [far])
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["trace"][0]["goal"]["gripper"], 10.0)

    def test_sends_bounded_goal_then_holds_measured_pose(self):
        controller = self.controller()
        action = pose()
        action["shoulder_pan"] = 8.0
        with (patch.object(holder, "assert_goal_echo"),
              patch.object(holder.select, "select", return_value=([], [], [])),
              patch.object(holder.time, "sleep")):
            result = holder.execute_actions(controller, "molmoact2", pose(), [action])
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["executedActions"], 1)
        self.assertEqual(controller.robot.bus.sync_write.call_count, 2)
        self.assertEqual(controller.robot.bus.sync_write.call_args_list[0].args,
                         ("Goal_Position", action))
        self.assertEqual(controller.robot.bus.sync_write.call_args_list[1].args,
                         ("Goal_Position", pose()))

    def test_tracking_lag_does_not_abort_any_policy(self):
        for model_id in holder.ACTION_RATES:
            with self.subTest(model_id=model_id):
                controller = self.controller()
                action = pose()
                action["gripper"] = 15.75
                with (patch.object(holder, "assert_goal_echo"),
                      patch.object(holder.select, "select", return_value=([], [], [])),
                      patch.object(holder.time, "sleep")):
                    result = holder.execute_actions(controller, model_id, pose(),
                                                    [action, action])
                self.assertEqual(result["status"], "executed")
                self.assertEqual(result["executedActions"], 2)
                self.assertEqual(result["trace"][0]["goal"]["gripper"], 10.0)
                self.assertEqual(result["trace"][1]["actual"]["gripper"], 0.0)

    def test_changed_measured_pose_does_not_reject_inference_block(self):
        controller = self.controller()
        measured = pose()
        measured["gripper"] = 10.12
        controller.read.side_effect = lambda register: measured
        action = pose()
        action["gripper"] = 15.75
        with (patch.object(holder, "assert_goal_echo"),
              patch.object(holder.select, "select", return_value=([], [], [])),
              patch.object(holder.time, "sleep")):
            result = holder.execute_actions(controller, "molmoact2", pose(), [action])
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["trace"][0]["actual"]["gripper"], 10.12)

    def test_held_pose_lag_does_not_abort_before_operator_release(self):
        controller = self.controller()
        lagging = pose()
        lagging["gripper"] = 10.12
        controller.read.side_effect = lambda register: lagging if register == "Present_Position" else pose()
        source = io.StringIO("r\n")
        with (patch.object(holder.sys, "stdin", source),
              patch.object(holder.select, "select", return_value=([source], [], []))):
            reason = holder.command_loop(controller, {}, Path("unused.json"))
        self.assertEqual(reason, "operator_release")

    def test_new_prompt_epoch_stops_remaining_actions_and_holds(self):
        controller = self.controller()
        action = pose()
        action["shoulder_pan"] = 8.0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "outputs"
            output.mkdir()
            epoch = output / "ui-robot-epoch-test.txt"
            epoch.write_text("0")
            def write(register, goal):
                if goal == action:
                    epoch.write_text("1")
            controller.robot.bus.sync_write.side_effect = write
            with (patch.object(holder, "ROOT", root),
                  patch.object(holder, "assert_goal_echo"),
                  patch.object(holder.select, "select", return_value=([], [], [])),
                  patch.object(holder.time, "sleep")):
                result = holder.execute_actions(controller, "molmoact2", pose(),
                                                [action, action], epoch_path=epoch, epoch=0)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["executedActions"], 1)
        self.assertEqual(controller.robot.bus.sync_write.call_count, 2)

    def test_file_backed_action_command_reaches_executor(self):
        controller = self.controller()
        action = pose()
        action["shoulder_pan"] = 4.0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "outputs"
            output.mkdir()
            actions = output / "ui-robot-actions-test.json"
            actions.write_text(json.dumps([action]))
            epoch = output / "ui-robot-epoch-test.txt"
            epoch.write_text("0")
            active_reply = output / "ui-robot-reply-active.json"
            reply = output / "ui-robot-reply-test.json"
            report = output / "report.json"
            active = {"op": "task_active", "reply_path": str(active_reply)}
            command = {"op": "execute", "model": "molmoact2", "actions_path": str(actions),
                       "epoch_path": str(epoch), "epoch": 0,
                       "observed_state": pose(), "reply_path": str(reply)}
            source = io.StringIO(json.dumps(active) + "\n" + json.dumps(command) + "\n")
            clock = [0.0]
            def ready(*_):
                if active_reply.exists():
                    clock[0] = 1000.0  # Past the idle hold limit during an active task.
                return ([source], [], []) if source.tell() < len(source.getvalue()) or reply.exists() else ([], [], [])
            with (patch.object(holder, "ROOT", root),
                  patch.object(holder.sys, "stdin", source),
                  patch.object(holder, "assert_goal_echo"),
                  patch.object(holder.select, "select", side_effect=ready),
                  patch.object(holder.time, "monotonic", side_effect=lambda: clock[0]),
                  patch.object(holder.time, "sleep")):
                reason = holder.command_loop(controller, {}, report)
            self.assertEqual(reason, "api_disconnected")
            self.assertEqual(json.loads(active_reply.read_text())["status"], "task_active")
            self.assertEqual(json.loads(reply.read_text())["status"], "executed")
            self.assertEqual(controller.robot.bus.sync_write.call_count, 2)

    def test_return_command_uses_current_holder_and_measured_hold(self):
        controller = self.controller()
        controller.saved = {"automatic_travel_validated": True}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "outputs"
            output.mkdir()
            reply = output / "ui-robot-reply-return.json"
            report = output / "report.json"
            source = io.StringIO(json.dumps({"op": "return_to_start", "reply_path": str(reply)}) + "\n")
            with (patch.object(holder, "ROOT", root),
                  patch.object(holder.sys, "stdin", source),
                  patch.object(holder.select, "select", return_value=([source], [], [])),
                  patch.object(holder, "move_monitored", return_value=pose()) as move,
                  patch.object(holder, "assert_goal_echo")):
                reason = holder.command_loop(controller, {"telemetry": []}, report)
            self.assertEqual(reason, "api_disconnected")
            self.assertEqual(json.loads(reply.read_text())["status"], "returned")
            move.assert_called_once_with(controller, [], already_holding=True)
            controller.robot.bus.sync_write.assert_called_once_with("Goal_Position", pose())
            controller.health.assert_called_with(expect_torque=1)

    def test_disconnect_without_operator_release_keeps_verified_torque(self):
        controller = self.controller()
        controller.robot.bus.disconnect = Mock()
        with patch.object(holder, "assert_goal_echo"):
            measured = holder._hold_and_disconnect(controller)
        self.assertEqual(measured, pose())
        controller.robot.bus.sync_write.assert_called_once_with("Goal_Position", pose())
        controller.health.assert_called_once_with(expect_torque=1)
        controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_controller_error_does_not_release_follower_torque(self):
        controller = self.controller()
        controller.saved = {"automatic_travel_validated": True}
        controller.target = pose()
        controller.armed = True
        controller.robot.bus.is_connected = True
        controller.robot.bus.disconnect = Mock()
        controller.close = Mock()
        controller.connect = Mock()
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            with (patch.object(holder, "FluxStartController", return_value=controller),
                  patch.object(holder, "move_monitored", return_value=pose()),
                  patch.object(holder, "command_loop", side_effect=RuntimeError("controller fault")),
                  patch.object(holder, "assert_goal_echo")):
                self.assertEqual(holder.run(report), 1)
            saved = json.loads(report.read_text())
        self.assertEqual(saved["outcome"], "aborted")
        self.assertEqual(saved["measured_at_disconnect"], pose())
        controller.close.assert_not_called()
        controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)


if __name__ == "__main__":
    unittest.main()
