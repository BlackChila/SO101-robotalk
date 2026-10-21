"""Offline intro audio and motor composition tests; no real playback or motors."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import demo_intro_replay as intro
from conversation_motion import prepare_intro_gripper, RealtimeIntroGripper
from intro_speech_envelope import IntroSpeechEnvelope


class IntroSpeechTests(unittest.TestCase):
    def setUp(self):
        self.pose = dict.fromkeys(intro.NAMES, 0.0)
        self.pose["gripper"] = 1.0
        self.bounds = dict.fromkeys(intro.NAMES, (-180, 180))
        self.bounds["gripper"] = (0, 100)

    def test_envelope_tracks_syllables_and_silence(self):
        envelope = IntroSpeechEnvelope(np.concatenate([
            np.zeros(3200), np.full(3200, 0.2), np.zeros(3200)]))
        self.assertEqual(envelope.level_at(0.1), 0)
        self.assertGreater(envelope.level_at(0.3), 0.9)
        self.assertEqual(envelope.level_at(0.58), 0)
        for elapsed in (None, -1, 0.6, 10, float('nan')):
            self.assertEqual(envelope.level_at(elapsed), 0)

    def test_invalid_audio_rejected(self):
        for samples in ([], [float('nan')], [[0, 1]]):
            with self.assertRaises(ValueError):
                IntroSpeechEnvelope(samples)

    def test_intro_uses_conversation_speed_caps_and_closes_after_audio(self):
        envelope = IntroSpeechEnvelope(np.full(16000, 0.2))
        with patch.object(IntroSpeechEnvelope, 'from_file', return_value=envelope):
            goal = prepare_intro_gripper({'audio': 'unused.mp3', 'start_pose': self.pose}, self.bounds)
        self.assertEqual(goal(0, None), 1)
        previous = 1
        for i in range(1, 51):
            value = goal(i * .02, i * .02 - .02)
            self.assertLessEqual(value - previous, 1.2 + 1e-9)
            self.assertLessEqual(value, 24.4 + 1e-9)
            previous = value
        self.assertGreater(previous, 20)
        for i in range(51, 81):
            value = goal(i * .02, None)
            self.assertLessEqual(previous - value, 1.5 + 1e-9)
            previous = value
        self.assertEqual(previous, 1)

    def run_replay(self, callback, play_audio=True):
        clock = [0.0]
        player = Mock(returncode=0)
        player.poll.return_value = None
        player.wait.side_effect = lambda **kw: player.poll.configure_mock(return_value=0)
        controller = SimpleNamespace(bounds=self.bounds, health=Mock(),
            read=Mock(return_value=self.pose),
            robot=SimpleNamespace(bus=SimpleNamespace(sync_write=Mock())))
        samples = [{'t': i * .02, 'target': {**self.pose, 'shoulder_pan': i, 'gripper': 80}}
                   for i in range(50)]
        take = {'audio': 'unused.mp3', 'lead_in_s': .1,
                'planned_duration_s': 1, 'audio_duration_s': .4}
        result = {}
        def sleep(delay):
            clock[0] += delay
        with patch.object(intro.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(intro.time, 'sleep', side_effect=sleep), \
             patch.object(intro.subprocess, 'Popen', return_value=player) as launch:
            intro.replay(controller, take, samples, result, gripper_goal=callback, play_audio=play_audio)
            if not play_audio:
                launch.assert_not_called()
        return controller, samples, result, player

    def test_audio_override_preserves_other_joints_and_original_recording(self):
        callback = Mock(side_effect=lambda now, elapsed: 1 if elapsed is None else 5)
        controller, samples, result, player = self.run_replay(callback)
        goals = [c.args[1] for c in controller.robot.bus.sync_write.call_args_list]
        for i, goal in enumerate(goals):
            self.assertEqual(goal['gripper'], 1 if i < 5 else 5)
            for name in intro.NAMES:
                if name != 'gripper':
                    self.assertEqual(goal[name], samples[i]['target'][name])
            self.assertEqual(samples[i]['target']['gripper'], 80)
        self.assertAlmostEqual(callback.call_args_list[5].args[1], 0)
        self.assertAlmostEqual(callback.call_args_list[6].args[1], .02)
        self.assertEqual(result['maximum_tracking_difference']['gripper'], 4)
        player.stderr.close.assert_called_once()

    def test_plain_replay_retains_recorded_gripper(self):
        controller, samples, _, _ = self.run_replay(None)
        self.assertEqual([c.args[1] for c in controller.robot.bus.sync_write.call_args_list],
                         [s['target'] for s in samples])

    def test_realtime_intro_replays_gesture_without_recorded_audio(self):
        controller, samples, result, _ = self.run_replay(lambda now, elapsed: 5, play_audio=False)
        self.assertNotIn('audio_launch_offset_s', result)
        self.assertNotIn('audio_exit_code', result)
        for goal, sample in zip(controller.robot.bus.sync_write.call_args_list, samples):
            self.assertEqual(goal.args[1], {**sample['target'], 'gripper': 5})

    def test_live_intro_levels_expire_and_disconnect_stops(self):
        commands = Mock(eof=False, poll=Mock(return_value=[]))
        speech = RealtimeIntroGripper({'start_pose': self.pose}, self.bounds, commands)
        self.assertEqual(speech(1, None), 1)
        commands.poll.return_value = [{'op': 'speech_level', 'level': 1, 'sent_at': 1.02}]
        opened = speech(1.02, None)
        self.assertGreater(opened, 1)
        commands.poll.return_value = []
        self.assertLess(speech(1.5, None), opened)
        commands.eof = True
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            speech(1.52, None)

    def test_override_outside_calibration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'gripper outside calibration'):
            self.run_replay(lambda now, elapsed: 101)


if __name__ == '__main__':
    unittest.main()
