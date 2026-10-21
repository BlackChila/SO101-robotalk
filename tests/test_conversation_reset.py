"""Controller reset sequencing; no device, network, or model access."""
import sys
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import asr_web


class ConversationResetTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.sid = 'a' * 32
        self.events = []
        self.lock = threading.Lock()
        self.motion = dict(sessionId=self.sid, active=True, state='task', returnRequested=False)
        for name, value in {'_conversation_robot_reset_session': None,
                            '_conversation_robot_reset_cancel': threading.Event(),
                            '_conversation_robot_reset_results': {},
                            '_realtime_motion_sessions': {self.sid},
                            '_active_task': {'conversationSessionId': self.sid},
                            '_policy_lock': self.lock}.items():
            self.stack.enter_context(patch.object(asr_web, name, value))
        self.stack.enter_context(patch.object(asr_web, 'conversation_motion_status',
                                              side_effect=lambda: dict(self.motion)))
        self.stack.enter_context(patch.object(asr_web.face_tracking_session, 'disable',
                                              side_effect=lambda _: self.events.append('gaze-off')))
        self.stop = self.stack.enter_context(patch.object(asr_web, 'request_physical_task_stop',
                                                        side_effect=self.stop_task))
        self.command = self.stack.enter_context(patch.object(asr_web, 'restart_conversation_motion',
                                                           side_effect=self.reset_command))
        self.policy = self.stack.enter_context(patch.object(asr_web, 'policy_session'))

    def stop_task(self):
        self.events.append('stop')
        self.motion['state'] = 'holding'
        asr_web._active_task = None

    def reset_command(self, sid):
        self.assertEqual(sid, self.sid)
        self.assertTrue(self.lock.locked())
        self.assertIsNone(asr_web._active_task)
        self.events.append('reset')
        return dict(status='reset', followerTorqueHolding=True, speechGripperAvailable=True, controllerRestarted=True)

    def call(self, origin='realtime-tool', call_id='call-1'):
        return asr_web.conversation_robot_reset(
            asr_web.ConversationRobotReset(sessionId=self.sid, callId=call_id),
            SimpleNamespace(headers={'x-so101-conversation': origin}))

    def test_restart_stops_task_first_keeps_model_and_deduplicates(self):
        result = self.call()
        self.assertEqual(self.events, ['gaze-off', 'stop', 'reset'])
        self.assertEqual(result['sessionId'], self.sid)
        self.assertFalse(result['modelReloaded'])
        self.assertEqual(self.call(), result)
        self.command.assert_called_once()
        self.assertEqual(self.policy.mock_calls, [])
        self.assertFalse(self.lock.locked())
        self.assertIsNone(asr_web._conversation_robot_reset_session)

    def test_button_uses_same_reset_without_requiring_realtime(self):
        asr_web._realtime_motion_sessions.clear()
        self.assertEqual(self.call('operator-reset')['status'], 'reset')

    def test_rejects_invalid_origin_expired_session_and_other_owner(self):
        with self.assertRaises(asr_web.HTTPException) as error:
            self.call('untrusted')
        self.assertEqual(error.exception.status_code, 403)
        asr_web._realtime_motion_sessions.clear()
        with self.assertRaises(asr_web.HTTPException):
            self.call()
        asr_web._active_task = {'conversationSessionId': 'b' * 32}
        with self.assertRaises(asr_web.HTTPException):
            self.call('operator-reset')
        self.stop.assert_not_called()
        self.command.assert_not_called()

    def test_unverified_hold_fails_and_releases_reset_lock(self):
        self.command.side_effect = None
        self.command.return_value = dict(status='reset', followerTorqueHolding=False)
        with self.assertRaises(asr_web.HTTPException):
            self.call()
        self.assertFalse(self.lock.locked())
        self.assertIsNone(asr_web._conversation_robot_reset_session)
        self.assertEqual(asr_web._conversation_robot_reset_results, {})
        self.assertEqual(self.policy.mock_calls, [])

    def test_conversation_ending_before_hold_cancels_return(self):
        def stop_and_end():
            self.stop_task()
            self.motion['returnRequested'] = True
        self.stop.side_effect = stop_and_end
        with self.assertRaises(asr_web.HTTPException):
            self.call()
        self.command.assert_not_called()
        self.assertFalse(self.lock.locked())
        self.assertIsNone(asr_web._conversation_robot_reset_session)

    def test_wait_timeout_does_not_unload_or_move(self):
        fake_lock = self.stack.enter_context(patch.object(asr_web, '_policy_lock'))
        fake_lock.acquire.return_value = False
        self.stack.enter_context(patch.object(asr_web.time, 'monotonic', side_effect=[0, 46]))
        with self.assertRaises(asr_web.HTTPException) as error:
            self.call()
        self.assertIn('Modell bleibt geladen', error.exception.detail)
        self.command.assert_not_called()
        fake_lock.release.assert_not_called()
        self.assertEqual(self.policy.mock_calls, [])

    def test_new_tasks_and_duplicate_resets_blocked_during_reset(self):
        asr_web._conversation_robot_reset_session = self.sid
        with self.assertRaises(asr_web.HTTPException):
            self.call()
        request = asr_web.ConversationTaskRequest(sessionId=self.sid, callId='task', instruction='Pick up the cup')
        with self.assertRaises(asr_web.HTTPException) as error:
            asr_web.conversation_task_start(request, SimpleNamespace(headers={'x-so101-conversation': 'realtime-tool'}))
        self.assertEqual(error.exception.status_code, 409)
        self.stop.assert_not_called()
        self.command.assert_not_called()


class ControllerRestartTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        import json
        from unittest.mock import Mock
        self.json = json
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / 'outputs').mkdir()
        self.sid = 'b' * 32
        self.path = self.root / 'outputs' / f'conversation-motion-{self.sid}.json'
        self.path.write_text(json.dumps({'state': 'holding'}))
        self.old = Mock(pid=101)
        self.old.poll.return_value = None
        self.old.stdin.fileno.return_value = 42
        self.new = Mock(pid=202)
        self.new.poll.return_value = None
        self.old.wait.side_effect = self.finish_old
        for name, value in {'ROOT': self.root, '_conversation_motion_process': self.old,
                            '_conversation_motion_report': self.path, '_conversation_motion_id': self.sid,
                            '_conversation_motion_fault': None, '_conversation_motion_return_requested': False,
                            '_conversation_robot_reset_session': self.sid,
                            '_conversation_robot_reset_cancel': threading.Event(),
                            '_realtime_motion_sessions': {self.sid}, '_active_task': None}.items():
            self.stack.enter_context(patch.object(asr_web, name, value))
        self.write = self.stack.enter_context(patch.object(asr_web.os, 'write', side_effect=lambda fd, data: len(data)))
        self.launch = self.stack.enter_context(patch.object(asr_web.subprocess, 'Popen', side_effect=self.start_new))
        self.policy = self.stack.enter_context(patch.object(asr_web, 'policy_session'))

    def finish_old(self, **kwargs):
        self.old.poll.return_value = 0
        self.path.write_text(self.json.dumps({'state': 'stopped', 'follower_torque_holding': True}))

    def start_new(self, args, **kwargs):
        self.assertEqual(self.old.poll(), 0, 'must wait for old process to exit')
        self.assertIn('--intro-end-pose', args)
        self.assertEqual(self.json.loads(self.path.read_text())['state'], 'starting')
        archives = list(self.path.parent.glob(f'{self.path.stem}-previous-*.json'))
        self.assertEqual(len(archives), 1)
        self.assertTrue(self.json.loads(archives[0].read_text())['follower_torque_holding'])
        self.path.write_text(self.json.dumps({'state': 'holding', 'initial_hold_verified': True,
                                              'speech_gripper_available': True, 'rest_pose': {'gripper': 1}}))
        return self.new

    def test_new_process_same_voice_session_only_after_verified_old_exit(self):
        result = asr_web.restart_conversation_motion(self.sid)
        self.assertTrue(result['controllerRestarted'])
        self.assertEqual((result['previousControllerPid'], result['controllerPid']), (101, 202))
        self.write.assert_called_once_with(42, b'{"op":"stop"}\n')
        self.assertIs(asr_web._conversation_motion_process, self.new)
        self.assertEqual(asr_web._conversation_motion_id, self.sid)
        self.assertIn(self.sid, asr_web._realtime_motion_sessions)
        self.assertEqual(self.policy.mock_calls, [])

    def test_unverified_old_hold_prevents_new_process(self):
        def unverified(**kwargs):
            self.finish_old()
            self.path.write_text(self.json.dumps({'state': 'failed', 'follower_torque_holding': False}))
        self.old.wait.side_effect = unverified
        with self.assertRaisesRegex(RuntimeError, 'nicht bestätigt'):
            asr_web.restart_conversation_motion(self.sid)
        self.launch.assert_not_called()

    def test_old_controller_timeout_prevents_second_motor_owner(self):
        self.old.wait.side_effect = asr_web.subprocess.TimeoutExpired('controller', 12)
        with self.assertRaisesRegex(RuntimeError, 'läuft noch'):
            asr_web.restart_conversation_motion(self.sid)
        self.launch.assert_not_called()
        self.assertIs(asr_web._conversation_motion_process, self.old)

    def test_end_during_disconnect_cancels_restart(self):
        def end_during_wait(**kwargs):
            self.finish_old()
            asr_web._conversation_robot_reset_cancel.set()
        self.old.wait.side_effect = end_during_wait
        with self.assertRaisesRegex(RuntimeError, 'abgebrochen'):
            asr_web.restart_conversation_motion(self.sid)
        self.launch.assert_not_called()

    def test_new_controller_failure_is_not_reported_as_ready(self):
        def fail_new(*args, **kwargs):
            self.start_new(*args, **kwargs)
            self.path.write_text(self.json.dumps({'state': 'failed', 'error': 'positioning failed',
                                                 'follower_torque_holding': True}))
            self.new.poll.return_value = 1
            return self.new
        self.launch.side_effect = fail_new
        with self.assertRaisesRegex(RuntimeError, 'positioning failed'):
            asr_web.restart_conversation_motion(self.sid)

    def test_heartbeat_and_speech_end_tolerate_handover_gap(self):
        request = asr_web.ConversationMotionSession(sessionId=self.sid)
        self.assertEqual(asr_web.conversation_motion_heartbeat(request)['status'], 'resetting')
        self.assertEqual(asr_web.conversation_motion_speech_end(request)['status'], 'resetting')
        self.write.assert_not_called()

    def test_launch_failure_preserves_old_verified_hold_report(self):
        self.launch.side_effect = OSError('launch failed')
        with self.assertRaisesRegex(OSError, 'launch failed'):
            asr_web.restart_conversation_motion(self.sid)
        report = self.json.loads(self.path.read_text())
        self.assertEqual(report['state'], 'stopped')
        self.assertTrue(report['follower_torque_holding'])
        self.assertIs(asr_web._conversation_motion_process, self.old)

    def test_cancel_after_launch_stops_replacement_controller(self):
        def launch_and_cancel(*args, **kwargs):
            result = self.start_new(*args, **kwargs)
            asr_web._conversation_robot_reset_cancel.set()
            return result
        self.launch.side_effect = launch_and_cancel
        with patch.object(asr_web, 'stop_conversation_motion') as stop:
            with self.assertRaisesRegex(RuntimeError, 'abgebrochen'):
                asr_web.restart_conversation_motion(self.sid)
            stop.assert_called_once_with(self.sid)

    def test_missing_new_hold_confirmation_times_out_and_stops_new_owner(self):
        def launch_unverified(*args, **kwargs):
            result = self.start_new(*args, **kwargs)
            self.path.write_text(self.json.dumps({'state': 'holding'}))
            return result
        self.launch.side_effect = launch_unverified
        with patch.object(asr_web.time, 'monotonic', side_effect=[0, 0, 151]), \
             patch.object(asr_web.time, 'sleep'), \
             patch.object(asr_web, 'stop_conversation_motion') as stop:
            with self.assertRaisesRegex(RuntimeError, 'nicht rechtzeitig bereit'):
                asr_web.restart_conversation_motion(self.sid)
            stop.assert_called_once_with(self.sid)
