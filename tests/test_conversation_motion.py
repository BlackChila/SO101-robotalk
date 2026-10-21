"""Offline checks for bounded, audio-reactive speech gripper gestures."""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import conversation_motion  # noqa: E402
from conversation_motion import SpeechGripperAnimator  # noqa: E402


class ConversationMotionTests(unittest.TestCase):
    def setUp(self) -> None:
        torque_limit = patch.object(conversation_motion, "limit_gripper_torque")
        torque_limit.start()
        self.addCleanup(torque_limit.stop)
        self.rest = {
            "shoulder_pan": -11.5, "shoulder_lift": -29.0,
            "elbow_flex": -2.5, "wrist_flex": 71.3,
            "wrist_roll": -0.5, "gripper": 1.3,
        }
        self.bounds = {name: (-180, 180) for name in self.rest}
        self.bounds["gripper"] = (0, 100)

    def test_five_hz_syllables_keep_moving_for_ten_minutes(self) -> None:
        animator = SpeechGripperAnimator(self.rest, self.bounds)
        previous = self.rest["gripper"]
        troughs, peaks = [], []
        for index in range(50 * 600):
            # Every 200 ms: a voiced peak followed by a syllable valley.
            level = 0.9 if index % 10 < 5 else 0.1
            goal = animator.goal(index / 50, level)
            self.assertEqual({k: v for k, v in goal.items() if k != "gripper"},
                             {k: v for k, v in self.rest.items() if k != "gripper"})
            self.assertLessEqual(abs(goal["gripper"] - previous), 1.5 + 1e-9)
            self.assertLessEqual(goal["gripper"], self.rest["gripper"] + 23.4)
            if index % 10 == 4:
                peaks.append(goal["gripper"])
            if index % 10 == 9:
                troughs.append(goal["gripper"])
            previous = goal["gripper"]
        self.assertEqual(len(peaks), 3000)
        # The first syllable starts at rest rather than the nonzero audio valley.
        self.assertGreater(peaks[0] - troughs[0], 3)
        self.assertTrue(all(peak - trough > 4 for peak, trough in zip(peaks[1:], troughs[1:])))

    def test_continuous_nonzero_audio_does_not_need_rearming(self) -> None:
        animator = SpeechGripperAnimator(self.rest, self.bounds)
        for index in range(100):
            animator.goal(index / 50, 0.6)
        middle = animator.current
        for index in range(100, 110):
            animator.goal(index / 50, 1.0)
        self.assertGreater(animator.current, middle + 2)
        for index in range(110, 120):
            animator.goal(index / 50, 0.4)
        self.assertLess(animator.current, middle)

    def test_silence_and_stale_audio_return_smoothly_to_rest(self) -> None:
        for silence in (None, 0.0):
            animator = SpeechGripperAnimator(self.rest, self.bounds)
            for index in range(10):
                animator.goal(index / 50, 1)
            previous = animator.current
            for index in range(10, 25):
                goal = animator.goal(index / 50, silence)
                self.assertLessEqual(abs(goal["gripper"] - previous), 1.5 + 1e-9)
                previous = goal["gripper"]
            self.assertEqual(previous, self.rest["gripper"])

    def test_invalid_calibration_and_time_are_rejected(self) -> None:
        for rest in (50, math.nan):
            with self.assertRaises(ValueError):
                SpeechGripperAnimator({**self.rest, "gripper": rest}, self.bounds)
        animator = SpeechGripperAnimator(self.rest, self.bounds)
        for now, level in ((math.nan, 0.5), (0, math.nan), (0, -0.1)):
            with self.assertRaises(ValueError):
                animator.goal(now, level)

    def test_opening_scales_with_calibrated_range(self) -> None:
        animator = SpeechGripperAnimator(self.rest, {**self.bounds, "gripper": (0, 80)})
        for index in range(100):
            animator.goal(index / 50, 1)
        self.assertAlmostEqual(animator.current, self.rest["gripper"] + 18.72)

    def test_wider_opening_retains_speed_and_absolute_opening_limits(self) -> None:
        animator = SpeechGripperAnimator(self.rest, self.bounds)
        previous = animator.current
        for index in range(50):
            goal = animator.goal(index / 50, 1.0)
            self.assertLessEqual(goal["gripper"] - previous, 1.2 + 1e-9)
            previous = goal["gripper"]
        self.assertAlmostEqual(previous - self.rest["gripper"], 18 * 1.3)
        higher_rest = SpeechGripperAnimator({**self.rest, "gripper": 10}, self.bounds)
        for index in range(50):
            higher_rest.goal(index / 50, 1.0)
        self.assertEqual(higher_rest.current, 26)

    def test_pipe_bursts_partial_lines_and_eof(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            reader = conversation_motion.MotionCommandReader(read_fd)
            os.write(write_fd, b'{"op":"heartbeat"}\n{"op":"speech_level","level":0.5}\n{"op":')
            self.assertEqual(reader.poll(), [{"op": "heartbeat"}, {"op": "speech_level", "level": 0.5}])
            self.assertEqual(reader.poll(), [])
            os.write(write_fd, b'"stop"}\n')
            self.assertEqual(reader.poll(), [{"op": "stop"}])
            os.close(write_fd)
            write_fd = None
            self.assertEqual(reader.poll(), [])
            self.assertTrue(reader.eof)
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    def test_command_burst_uses_latest_level_then_stops(self) -> None:
        controller = SimpleNamespace(bounds=self.bounds, health=Mock(),
            robot=SimpleNamespace(bus=SimpleNamespace(sync_write=Mock())))
        reader = Mock(eof=False)
        reader.poll.side_effect = [
            [{"op": "speech_level", "level": 1}, {"op": "speech_level", "level": 0}],
            [{"op": "stop"}],
        ]
        with patch.object(conversation_motion, "MotionCommandReader", return_value=reader), \
             patch.object(conversation_motion.sys, "stdin", Mock()), \
             patch.object(conversation_motion.time, "sleep"):
            self.assertEqual(conversation_motion.hold_and_animate(controller, self.rest), "operator_stop")
        controller.robot.bus.sync_write.assert_not_called()

    def test_delayed_pipe_audio_cannot_start_a_gesture(self) -> None:
        controller = SimpleNamespace(bounds=self.bounds, health=Mock(),
            robot=SimpleNamespace(bus=SimpleNamespace(sync_write=Mock())))
        reader = Mock(eof=False)
        reader.poll.side_effect = [[{"op": "speech_level", "level": 1, "sent_at": 0}], [{"op": "stop"}]]
        with patch.object(conversation_motion, "MotionCommandReader", return_value=reader), \
             patch.object(conversation_motion.sys, "stdin", Mock()), \
             patch.object(conversation_motion.time, "monotonic", return_value=10), \
             patch.object(conversation_motion.time, "sleep"):
            conversation_motion.hold_and_animate(controller, self.rest)
        controller.robot.bus.sync_write.assert_not_called()

    def run_tracking_commands(self, batches, *, held=None):
        """Exercise the real owner loop with deterministic time and a fake bus."""
        measured = (held or self.rest).copy()
        echoed_goal = measured.copy()
        controller = SimpleNamespace(bounds=self.bounds, health=Mock(),
            read=Mock(side_effect=lambda register: (echoed_goal if register == "Goal_Position"
                                                   else measured).copy()),
            robot=SimpleNamespace(bus=SimpleNamespace(sync_write=Mock(
                side_effect=lambda register, goal: echoed_goal.update(goal)))))
        clock = [10.0]
        batches = iter(batches)

        def poll():
            clock[0] += 0.02
            batch = next(batches)
            for command in batch:
                if command["op"] == "face_observation":
                    command["observation"]["captured_at"] = clock[0]
            return batch

        reader = Mock(eof=False)
        reader.poll.side_effect = poll
        report = {}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "MotionCommandReader", return_value=reader), \
             patch.object(conversation_motion.sys, "stdin", Mock()), \
             patch.object(conversation_motion.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(conversation_motion.time, "sleep"), \
             patch.object(conversation_motion, "establish_measured_hold",
                          return_value=(held or self.rest).copy()) as hold, \
             patch.object(conversation_motion, "_save_reply") as reply:
            result = conversation_motion.hold_and_animate(
                controller, self.rest, report, Path(directory) / "report.json", start_pose=self.rest)
        return controller, hold, reply, report, result

    @staticmethod
    def face_observation(sequence=1):
        return {"op": "face_observation", "observation": {
            "sequence": sequence, "detected": True, "x": 0.99, "y": 0.9, "confidence": 0.95}}

    def test_gaze_and_speech_share_one_goal_without_resetting_gaze_or_wrist_roll(self):
        controller, hold, _, _, result = self.run_tracking_commands([
            [{"op": "face_tracking", "enabled": True}],
            [self.face_observation(), {"op": "speech_level", "level": 1}],
            [{"op": "speech_level", "level": 0.8}],
            [{"op": "stop"}],
        ])
        self.assertEqual(result, "operator_stop")
        hold.assert_called_once_with(controller)
        goals = [call.args[1] for call in controller.robot.bus.sync_write.call_args_list]
        self.assertEqual(len(goals), 2)
        for goal in goals:
            self.assertGreater(goal["shoulder_pan"], self.rest["shoulder_pan"])
            self.assertGreater(goal["wrist_flex"], self.rest["wrist_flex"])
            self.assertGreater(goal["gripper"], self.rest["gripper"])
            for axis in ("shoulder_lift", "elbow_flex", "wrist_roll"):
                self.assertEqual(goal[axis], self.rest[axis])
        self.assertGreater(goals[1]["shoulder_pan"], goals[0]["shoulder_pan"])

    def test_vertical_face_corrections_continue_while_speaking_without_search(self):
        for y, direction in ((0.03, -1), (0.97, 1), (0.5, 0)):
            with self.subTest(y=y):
                observation = self.face_observation()
                observation["observation"].update(x=0.90, y=y)
                controller, _, _, _, _ = self.run_tracking_commands([
                    [{"op": "face_tracking", "enabled": True, "search": False}],
                    [observation, {"op": "speech_level", "level": 1}],
                    [{"op": "speech_level", "level": 0.8}],
                    [{"op": "stop"}],
                ])
                goals = [c.args[1] for c in controller.robot.bus.sync_write.call_args_list]
                self.assertEqual(len(goals), 2)
                for goal in goals:
                    delta = goal["wrist_flex"] - self.rest["wrist_flex"]
                    if direction:
                        self.assertGreater(direction * delta, 0)
                    else:
                        self.assertEqual(delta, 0)
                    self.assertEqual(goal["shoulder_pan"], self.rest["shoulder_pan"])
                    self.assertGreater(goal["gripper"], self.rest["gripper"])

    def test_head_tilt_is_composed_with_gaze_and_stops_at_disable(self):
        with patch.object(conversation_motion, "HeadTiltAnimator") as tilt_type:
            tilt_type.return_value.goal.side_effect = lambda now, measured, active: measured + 1 if active else measured
            controller, hold, _, _, _ = self.run_tracking_commands([
                [{"op": "face_tracking", "enabled": True}],
                [self.face_observation()],
                [{"op": "face_tracking", "enabled": False}],
                [],
                [{"op": "stop"}],
            ])
        self.assertEqual(tilt_type.return_value.goal.call_count, 2)
        goals = [item.args[1] for item in controller.robot.bus.sync_write.call_args_list]
        self.assertEqual(goals[0]["wrist_roll"], self.rest["wrist_roll"] + 1)
        self.assertGreater(goals[0]["shoulder_pan"], self.rest["shoulder_pan"])
        self.assertEqual(hold.call_count, 2)

    def test_explicit_disable_holds_measured_pose_and_drops_pending_observations(self):
        controller, hold, _, report, _ = self.run_tracking_commands([
            [{"op": "face_tracking", "enabled": True}],
            [self.face_observation()],
            [{"op": "face_tracking", "enabled": False}, self.face_observation(2)],
            [],
            [{"op": "stop"}],
        ])
        self.assertEqual(hold.call_count, 2)
        self.assertFalse(report["face_tracking"]["enabled"])
        self.assertEqual(controller.robot.bus.sync_write.call_count, 1)

    def test_gaze_toggle_mid_speech_preserves_neutral_mouth_and_held_arm(self):
        held = {**self.rest, "gripper": 22, "shoulder_pan": 5, "wrist_flex": 55,
                "shoulder_lift": -20}
        controller, hold, _, report, _ = self.run_tracking_commands([
            [{"op": "speech_level", "level": 1}],
            [{"op": "face_tracking", "enabled": True, "request_id": "enable-1"}],
            [self.face_observation()],
            [{"op": "face_tracking", "enabled": False, "request_id": "disable-2"}],
            [],
            [{"op": "speech_end"}],
            *[[] for _ in range(25)],
            [{"op": "stop"}],
        ], held=held)
        self.assertEqual(hold.call_count, 2)
        self.assertTrue(report["speech_gripper_available"])
        self.assertEqual(report["face_tracking"]["request_id"], "disable-2")
        goals = [item.args[1] for item in controller.robot.bus.sync_write.call_args_list]
        # First write precedes tracking. Later writes preserve the held pose,
        # including a shoulder position that differs from the original rest.
        for goal in goals[1:]:
            for axis in ("shoulder_lift", "elbow_flex", "wrist_roll"):
                self.assertEqual(goal[axis], held[axis])
        self.assertGreater(goals[1]["gripper"], held["gripper"])
        self.assertLessEqual(goals[1]["gripper"] - held["gripper"], 1.2 + 1e-9)
        self.assertEqual(goals[-1]["gripper"], self.rest["gripper"])
        self.assertEqual(goals[-1]["shoulder_pan"], held["shoulder_pan"])
        self.assertEqual(goals[-1]["wrist_flex"], held["wrist_flex"])

    def test_rebase_keeps_speech_neutral_and_limits_after_measured_open_hold(self):
        animator = SpeechGripperAnimator(self.rest, self.bounds)
        old_cap = animator.open_high
        animator.rebase({**self.rest, "gripper": 23, "shoulder_pan": 7}, 1)
        self.assertEqual(animator.goal(1, 0)["gripper"], 23)
        self.assertEqual(animator.rest["gripper"], self.rest["gripper"])
        self.assertEqual(animator.open_high, old_cap)
        self.assertEqual(animator.goal(1.02, 0)["gripper"], 21.5)
        self.assertEqual(animator.rest["shoulder_pan"], 7)

    def test_stale_camera_discards_gaze_lead_and_holds_without_searching(self):
        controller, _, _, report, _ = self.run_tracking_commands([
            [{"op": "face_tracking", "enabled": True, "request_id": "camera-run"}],
            [self.face_observation()],
            *[[] for _ in range(60)],
            [{"op": "stop"}],
        ])
        final_goal = controller.robot.bus.sync_write.call_args.args[1]
        self.assertEqual(final_goal, self.rest)
        self.assertEqual(report["face_tracking"]["state"], "camera_stale")
        self.assertEqual(report["face_tracking"]["request_id"], "camera-run")

    def test_rejected_gaze_goal_echo_propagates_to_session_cleanup(self):
        with patch.object(conversation_motion, "assert_goal_echo",
                          side_effect=RuntimeError("goal not confirmed")):
            with self.assertRaisesRegex(RuntimeError, "goal not confirmed"):
                self.run_tracking_commands([
                    [{"op": "face_tracking", "enabled": True}],
                    [self.face_observation()],
                ])

    def test_task_handoff_flushes_tracking_and_cannot_reenable_during_task(self):
        controller, hold, reply, report, _ = self.run_tracking_commands([
            [{"op": "face_tracking", "enabled": True}],
            [self.face_observation()],
            [{"op": "task_active", "reply_path": "/tmp/test-unused-reply"},
             {"op": "face_tracking", "enabled": True}, self.face_observation(2)],
            [{"op": "task_inactive", "reply_path": "/tmp/test-unused-reply"},
             self.face_observation(3)],
            [{"op": "stop"}],
        ])
        self.assertEqual(hold.call_count, 3)
        self.assertEqual(reply.call_count, 2)
        self.assertFalse(report["face_tracking"]["enabled"])
        self.assertEqual(controller.robot.bus.sync_write.call_count, 1)

    def test_in_place_reset_returns_to_start_and_accepts_another_task(self):
        with patch.object(conversation_motion, "move_to_recorded_start", return_value={}) as move, \
             patch.object(conversation_motion, "verify_recorded_start", return_value=self.rest) as verify:
            controller, hold, replies, report, result = self.run_tracking_commands([
                [{"op": "reset_to_start", "reply_path": "/tmp/test-unused-reply"}],
                [{"op": "task_active", "reply_path": "/tmp/test-unused-reply"}],
                [{"op": "task_inactive", "reply_path": "/tmp/test-unused-reply"}],
                [{"op": "stop"}],
            ])
        self.assertEqual(result, "operator_stop")
        move.assert_called_once_with(controller, self.rest, speed_multiplier=4.0)
        verify.assert_called_once_with(controller, self.rest)
        self.assertEqual(replies.call_args_list[0].args[1]['status'], 'reset')
        self.assertTrue(replies.call_args_list[0].args[1]['followerTorqueHolding'])
        self.assertEqual(report['state'], 'holding')
        self.assertEqual(report['rest_pose'], self.rest)

    def test_failed_in_place_reset_never_resumes_old_targets(self):
        with patch.object(conversation_motion, "move_to_recorded_start", side_effect=RuntimeError('move failed')):
            with self.assertRaisesRegex(RuntimeError, 'move failed'):
                self.run_tracking_commands([
                    [{"op": "reset_to_start", "reply_path": "/tmp/test-unused-reply"}],
                    [{"op": "speech_level", "level": 1}],
                ])

    def test_invalid_wrist_roll_blocks_gaze_without_stopping_conversation(self):
        controller, _, _, report, result = self.run_tracking_commands([
            [{"op": "face_tracking", "enabled": True, "request_id": "invalid-roll"}],
            [self.face_observation()],
            [{"op": "stop"}],
        ], held={**self.rest, "wrist_roll": 83})
        self.assertEqual(result, "operator_stop")
        self.assertFalse(report["face_tracking"]["enabled"])
        self.assertEqual(report["face_tracking"]["state"], "blocked")
        self.assertIn("natural wrist roll", report["face_tracking"]["error"])
        self.assertEqual(report["face_tracking"]["request_id"], "invalid-roll")
        controller.robot.bus.sync_write.assert_not_called()

    def test_live_intro_handoff_preserves_neutral_when_mouth_is_open(self):
        commands = Mock(eof=False, poll=Mock(return_value=[{'op': 'stop'}]))
        speech = conversation_motion.RealtimeIntroGripper({'start_pose': self.rest}, self.bounds, commands)
        measured = {**self.rest, 'gripper': 22.0}
        controller = SimpleNamespace(bounds=self.bounds)
        reason = conversation_motion.hold_and_animate(controller, measured, intro_speech=speech)
        self.assertEqual(reason, 'operator_stop')
        self.assertEqual(speech.animator.rest['gripper'], self.rest['gripper'])
        self.assertEqual(speech.animator.current, 22.0)

    def test_live_voice_intro_never_prepares_or_plays_recorded_speech(self):
        controller = SimpleNamespace(bounds=self.bounds,
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True, disconnect=Mock())))
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, 'FluxStartController', return_value=controller), \
             patch.object(conversation_motion, 'load_take', return_value=({'start_pose': self.rest}, [])), \
             patch.object(conversation_motion, 'MotionCommandReader'), \
             patch.object(conversation_motion, 'connect_follower'), \
             patch.object(conversation_motion, 'move_to_recorded_start', return_value={}), \
             patch.object(conversation_motion, 'verify_recorded_start', return_value=self.rest), \
             patch.object(conversation_motion, 'prepare_intro_gripper') as recorded_speech, \
             patch.object(conversation_motion, 'replay') as replay, \
             patch.object(conversation_motion, 'establish_measured_hold', return_value=self.rest), \
             patch.object(conversation_motion, 'hold_and_animate', return_value='operator_stop'):
            result = conversation_motion.run(Path(directory) / 'report.json',
                                             Path(directory) / 'take.json', realtime_intro=True)
        self.assertEqual(result, 0)
        recorded_speech.assert_not_called()
        self.assertFalse(replay.call_args.kwargs['play_audio'])
        controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_normal_call_end_returns_to_take_start_then_holds(self) -> None:
        controller = SimpleNamespace(
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True, disconnect=Mock())),
            bounds=self.bounds,
        )
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "FluxStartController", return_value=controller), \
             patch.object(conversation_motion, "load_take", return_value=(
                 {"start_pose": self.rest}, [])), \
             patch.object(conversation_motion, "connect_follower"), \
             patch.object(conversation_motion, "move_to_recorded_start", return_value={}) as move, \
             patch.object(conversation_motion, "prepare_intro_gripper", return_value=Mock()), \
             patch.object(conversation_motion, "replay"), \
             patch.object(conversation_motion, "establish_measured_hold", return_value=self.rest), \
             patch.object(conversation_motion, "hold_and_animate", return_value="operator_return"), \
             patch.object(conversation_motion, "verify_recorded_start", return_value=self.rest) as verify:
            report_path = Path(directory) / "call.json"
            self.assertEqual(conversation_motion.run(report_path, Path(directory) / "take.json"), 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["returned_to_start"])
            self.assertTrue(report["follower_torque_holding"])
            self.assertEqual(move.call_count, 2)
            self.assertEqual(move.call_args_list,
                             [call(controller, self.rest, speed_multiplier=4.0, check_interrupt=ANY),
                              call(controller, self.rest, speed_multiplier=4.0)])
            self.assertEqual(verify.call_args_list, [call(controller, self.rest)] * 2)
            controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_end_during_positioning_or_intro_holds_before_returning(self) -> None:
        for phase in ("positioning", "intro", "realtime_intro"):
            for op in ("return_to_start", "stop"):
                with self.subTest(phase=phase, op=op), tempfile.TemporaryDirectory() as directory:
                    events = []
                    controller = SimpleNamespace(bounds=self.bounds,
                        robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True,
                            disconnect=Mock(side_effect=lambda **kw: events.append("disconnect")))))
                    reader = Mock(eof=False)
                    reader.poll.return_value = [{"op": op}]
                    initial_move = True

                    def move(*args, check_interrupt=None, **kwargs):
                        nonlocal initial_move
                        if initial_move:
                            initial_move = False
                            if phase == "positioning":
                                check_interrupt()
                        events.append("return" if check_interrupt is None else "positioning")
                        return {}

                    def replay(*args, gripper_goal=None, check_interrupt=None, **kwargs):
                        if phase == "realtime_intro":
                            gripper_goal(1.0, None)
                        else:
                            check_interrupt()

                    with patch.object(conversation_motion, "FluxStartController", return_value=controller), \
                         patch.object(conversation_motion, "load_take", return_value=({"start_pose": self.rest}, [])), \
                         patch.object(conversation_motion, "MotionCommandReader", return_value=reader), \
                         patch.object(conversation_motion, "connect_follower"), \
                         patch.object(conversation_motion, "prepare_intro_gripper", return_value=Mock()), \
                         patch.object(conversation_motion, "move_to_recorded_start", side_effect=move), \
                         patch.object(conversation_motion, "replay", side_effect=replay), \
                         patch.object(conversation_motion, "hold_and_animate") as animate, \
                         patch.object(conversation_motion, "verify_recorded_start", return_value=self.rest), \
                         patch.object(conversation_motion, "establish_measured_hold",
                                      side_effect=lambda _: events.append("hold") or self.rest):
                        path = Path(directory) / "report.json"
                        self.assertEqual(conversation_motion.run(path, Path("take.json"),
                                         realtime_intro=phase == "realtime_intro"), 0)
                    report = json.loads(path.read_text())
                    self.assertEqual(report["state"], "stopped")
                    self.assertTrue(report["follower_torque_holding"])
                    self.assertEqual(report.get("returned_to_start", False), op == "return_to_start")
                    if op == "return_to_start":
                        self.assertLess(events.index("hold"), events.index("return"))
                    else:
                        self.assertNotIn("return", events)
                    animate.assert_not_called()
                    controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_disconnect_holds_in_place_without_return(self) -> None:
        controller = SimpleNamespace(
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True, disconnect=Mock())),
            bounds=self.bounds,
        )
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "FluxStartController", return_value=controller), \
             patch.object(conversation_motion, "load_take", return_value=(
                 {"start_pose": self.rest}, [])), \
             patch.object(conversation_motion, "connect_follower"), \
             patch.object(conversation_motion, "move_to_recorded_start", return_value={}) as move, \
             patch.object(conversation_motion, "prepare_intro_gripper", return_value=Mock()), \
             patch.object(conversation_motion, "replay"), \
             patch.object(conversation_motion, "establish_measured_hold", return_value=self.rest), \
             patch.object(conversation_motion, "hold_and_animate", return_value="api_disconnected"), \
             patch.object(conversation_motion, "verify_recorded_start",
                          return_value=self.rest) as verify:
            report_path = Path(directory) / "call.json"
            self.assertEqual(conversation_motion.run(report_path, Path(directory) / "take.json"), 0)
            report = json.loads(report_path.read_text())
            self.assertNotIn("returned_to_start", report)
            self.assertTrue(report["follower_torque_holding"])
            move.assert_called_once_with(controller, self.rest, speed_multiplier=4.0, check_interrupt=ANY)
            verify.assert_called_once_with(controller, self.rest)

    def test_skip_intro_verifies_pre_intro_pose_then_holds_without_replay(self) -> None:
        controller = SimpleNamespace(
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True, disconnect=Mock())),
            bounds=self.bounds,
        )
        events = []
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "FluxStartController", return_value=controller), \
             patch.object(conversation_motion, "load_take", return_value=({"start_pose": self.rest}, [])), \
             patch.object(conversation_motion, "connect_follower"), \
             patch.object(conversation_motion, "move_to_recorded_start", side_effect=lambda *a, **k: events.append('move') or {}), \
             patch.object(conversation_motion, "verify_recorded_start", side_effect=lambda *a: events.append('verify') or self.rest), \
             patch.object(conversation_motion, "prepare_intro_gripper", return_value=Mock()), \
             patch.object(conversation_motion, "replay") as replay, \
             patch.object(conversation_motion, "establish_measured_hold", return_value=self.rest), \
             patch.object(conversation_motion, "hold_and_animate", side_effect=lambda *a, **k: events.append('conversation') or 'operator_return'):
            report_path = Path(directory) / "call.json"
            self.assertEqual(conversation_motion.run(report_path, Path(directory) / "take.json", skip_intro=True), 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report['intro_skipped'])
            self.assertEqual(report['rest_pose'], self.rest)
            self.assertTrue(report['returned_to_start'])
            self.assertTrue(report['follower_torque_holding'])
            self.assertEqual(events, ['move', 'verify', 'conversation', 'move', 'verify'])
            replay.assert_not_called()
            controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_intro_end_reset_holds_measured_pose_without_exact_target_check(self) -> None:
        end = {**self.rest, "shoulder_lift": -28.0, "elbow_flex": -3.0}
        measured = {**end, "elbow_flex": 0.2}
        controller = SimpleNamespace(
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True, disconnect=Mock())),
            bounds=self.bounds,
        )
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "FluxStartController", return_value=controller), \
             patch.object(conversation_motion, "load_take", return_value=(
                 {"start_pose": self.rest}, [{"target": end}])), \
             patch.object(conversation_motion, "connect_follower"), \
             patch.object(conversation_motion, "move_to_recorded_start", return_value={}) as move, \
             patch.object(conversation_motion, "verify_recorded_start") as verify, \
             patch.object(conversation_motion, "replay") as replay, \
             patch.object(conversation_motion, "establish_measured_hold", return_value=measured), \
             patch.object(conversation_motion, "hold_and_animate", return_value="api_disconnected"):
            report_path = Path(directory) / "reset.json"
            self.assertEqual(conversation_motion.run(
                report_path, Path(directory) / "take.json", intro_end_pose=True), 0)
            report = json.loads(report_path.read_text())
        move.assert_called_once_with(controller, end, speed_multiplier=4.0, check_interrupt=ANY)
        verify.assert_not_called()
        replay.assert_not_called()
        self.assertEqual(report["positioning_measured_end"], measured)
        self.assertTrue(report["initial_hold_verified"])
        self.assertTrue(report["follower_torque_holding"])
        controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_intro_waits_for_measured_start_after_faster_positioning(self) -> None:
        controller = SimpleNamespace(
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True, disconnect=Mock())),
            bounds=self.bounds,
        )
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "FluxStartController", return_value=controller), \
             patch.object(conversation_motion, "load_take", return_value=(
                 {"start_pose": self.rest}, [])), \
             patch.object(conversation_motion, "connect_follower"), \
             patch.object(conversation_motion, "move_to_recorded_start", return_value={}), \
             patch.object(conversation_motion, "verify_recorded_start",
                          side_effect=RuntimeError("start not reached")), \
             patch.object(conversation_motion, "prepare_intro_gripper", return_value=Mock()), \
             patch.object(conversation_motion, "replay") as replay, \
             patch.object(conversation_motion, "establish_measured_hold", return_value=self.rest):
            report_path = Path(directory) / "call.json"
            for skip in (False, True):
                self.assertEqual(conversation_motion.run(report_path, Path(directory) / "take.json", skip_intro=skip), 1)
                report = json.loads(report_path.read_text())
                self.assertEqual(report["state"], "failed")
                self.assertTrue(report["follower_torque_holding"])
                replay.assert_not_called()

    def test_intro_decode_failure_happens_before_connecting_or_moving(self) -> None:
        controller = SimpleNamespace(bounds=self.bounds,
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=False)))
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "FluxStartController", return_value=controller), \
             patch.object(conversation_motion, "load_take", return_value=({"start_pose": self.rest}, [])), \
             patch.object(conversation_motion, "prepare_intro_gripper", side_effect=RuntimeError("decode failed")), \
             patch.object(conversation_motion, "connect_follower") as connect, \
             patch.object(conversation_motion, "move_to_recorded_start") as move:
            path = Path(directory) / 'report.json'
            self.assertEqual(conversation_motion.run(path, Path('unused.json')), 1)
            self.assertIn('decode failed', json.loads(path.read_text())['error'])
            connect.assert_not_called()
            move.assert_not_called()

    def test_recovered_return_moves_to_recorded_start_and_keeps_torque(self) -> None:
        controller = SimpleNamespace(
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True, disconnect=Mock())),
            bounds=self.bounds,
        )
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "FluxStartController", return_value=controller), \
             patch.object(conversation_motion, "load_take", return_value=(
                 {"start_pose": self.rest}, [])), \
             patch.object(conversation_motion, "connect_follower"), \
             patch.object(conversation_motion, "move_to_recorded_start", return_value={}) as move, \
             patch.object(conversation_motion, "verify_recorded_start", return_value=self.rest) as verify, \
             patch.object(conversation_motion, "establish_measured_hold", return_value=self.rest):
            report_path = Path(directory) / "return.json"
            self.assertEqual(conversation_motion.return_only(report_path, Path(directory) / "take.json"), 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["returned_to_start"])
            self.assertTrue(report["follower_torque_holding"])
            move.assert_called_once_with(controller, self.rest, speed_multiplier=4.0)
            verify.assert_called_once_with(controller, self.rest)
            controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_recovered_return_failure_still_holds_measured_pose(self) -> None:
        controller = SimpleNamespace(
            robot=SimpleNamespace(bus=SimpleNamespace(is_connected=True, disconnect=Mock())),
            bounds=self.bounds,
        )
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(conversation_motion, "FluxStartController", return_value=controller), \
             patch.object(conversation_motion, "load_take", return_value=(
                 {"start_pose": self.rest}, [])), \
             patch.object(conversation_motion, "connect_follower"), \
             patch.object(conversation_motion, "move_to_recorded_start",
                          side_effect=RuntimeError("tracking failed")), \
             patch.object(conversation_motion, "establish_measured_hold",
                          return_value=self.rest) as hold:
            report_path = Path(directory) / "return.json"
            self.assertEqual(conversation_motion.return_only(report_path, Path(directory) / "take.json"), 1)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["state"], "failed")
            self.assertTrue(report["follower_torque_holding"])
            hold.assert_called_once_with(controller)
            controller.robot.bus.disconnect.assert_called_once_with(disable_torque=False)


if __name__ == "__main__":
    unittest.main()
