"""Motor-ownership and cancellation checks, without hardware or models."""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from face_tracking_session import FaceTrackingSession


class FaceTrackingSessionTests(unittest.TestCase):
    def setUp(self):
        self.camera = Mock(model_id='conversation')
        self.camera.face_tracking.return_value = {'running': True, 'observation': None}
        self.motion = {'active': True, 'state': 'holding', 'sessionId': 'call', 'faceTracking': {}}
        self.sent = []
        self.busy = False
        self.session = FaceTrackingSession(self.camera, lambda: self.motion,
            lambda session, command: self.sent.append((session, command)), lambda: self.busy)

    def tearDown(self):
        self.session.disable()

    def test_preview_never_sends_motor_commands(self):
        self.assertEqual(self.session.command('preview')['mode'], 'preview')
        self.assertEqual(self.sent, [])

    def test_enable_requires_current_held_owner_and_no_task(self):
        for changes in ({'active': False}, {'state': 'intro'}, {'sessionId': 'other'}, {'taskWasStarted': True}, {'returnRequested': True}):
            original = self.motion.copy()
            self.motion.update(changes)
            with self.assertRaises(RuntimeError): self.session.command('enable', 'call')
            self.motion = original
        self.busy = True
        with self.assertRaises(RuntimeError): self.session.command('enable', 'call')
        self.assertEqual(self.sent, [])

    def test_missing_model_does_not_enable_motor(self):
        self.camera.face_tracking.return_value = {'running': False, 'error': 'Install detector model'}
        with self.assertRaisesRegex(RuntimeError, 'Install detector'): self.session.command('enable', 'call')
        self.assertEqual(self.sent, [])
        self.assertEqual(self.session.status()['error'], 'Install detector model')

    def test_observation_is_forwarded_once_and_disable_cannot_rearm(self):
        event = threading.Event()
        def send(session, command):
            self.sent.append((session, command))
            if command['op'] == 'face_observation': event.set()
        self.session.send_motion = send
        observation = {'sequence': 1, 'captured_at': time.monotonic(), 'detected': True, 'x': .7, 'y': .4, 'confidence': .99}
        self.camera.face_tracking.return_value = {'running': True, 'observation': observation}
        self.session.command('enable', 'call', search=False, search_direction='left')
        self.assertEqual(self.sent[0][1]['search_direction'], 'left')
        self.assertTrue(event.wait(1))
        self.session.disable()
        self.session.thread.join(1)
        ops = [command['op'] for _, command in self.sent]
        self.assertEqual(ops, ['face_tracking', 'face_observation', 'face_tracking'])
        self.assertFalse(self.sent[-1][1]['enabled'])
        self.assertEqual(self.session.mode, 'preview')

    def test_inflight_camera_reply_cannot_forward_after_disable(self):
        entered, release = threading.Event(), threading.Event()
        def camera(action):
            if threading.current_thread().name == 'conversation-face-tracking':
                entered.set(); release.wait(2)
            return {'running': True, 'observation': {'sequence': 1}}
        self.camera.face_tracking.side_effect = camera
        self.session.command('enable', 'call')
        self.assertTrue(entered.wait(1))
        self.session.disable(); release.set(); self.session.thread.join(1)
        self.assertEqual([command['op'] for _, command in self.sent], ['face_tracking', 'face_tracking'])

    def test_task_appearance_disables_and_requires_explicit_reenable(self):
        self.session.command('enable', 'call')
        self.busy = True
        self.session.thread.join(1)
        self.assertFalse(self.session.thread.is_alive())
        self.assertEqual(self.session.mode, 'preview')
        self.assertFalse(self.sent[-1][1]['enabled'])
        self.busy = False
        self.assertEqual(self.session.mode, 'preview')

    def test_detector_failure_disables_motion(self):
        self.session.command('enable', 'call')
        self.camera.face_tracking.return_value = {'running': False, 'error': 'Camera stalled'}
        self.session.thread.join(1)
        self.assertEqual(self.session.error, 'Camera stalled')
        self.assertFalse(self.sent[-1][1]['enabled'])

    def test_disable_during_detector_start_cancels_pending_enable(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def camera(action):
            if action == 'start':
                entered.set(); release.wait(2)
            return {'running': True, 'observation': None}
        self.camera.face_tracking.side_effect = camera
        def enable():
            try: self.session.command('enable', 'call')
            except RuntimeError as exc: errors.append(str(exc))
        pending = threading.Thread(target=enable)
        pending.start()
        self.assertTrue(entered.wait(1))
        self.session.disable('operator stop')
        release.set(); pending.join(1)
        self.assertFalse(pending.is_alive())
        self.assertEqual(self.sent, [])
        self.assertTrue(errors)
        self.assertNotEqual(self.session.mode, 'tracking')

    def test_rejected_motor_enable_is_reported_and_stops_forwarding(self):
        def send(session, command):
            self.sent.append((session, command))
            if command.get('enabled'):
                self.motion['faceTracking'] = {'request_id': command['request_id'],
                    'state': 'blocked', 'error': 'Wrist roll is not natural'}
        self.session.send_motion = send
        self.session.command('enable', 'call')
        self.session.thread.join(1)
        self.assertEqual(self.session.mode, 'preview')
        self.assertEqual(self.session.error, 'Wrist roll is not natural')
        self.assertFalse(self.sent[-1][1]['enabled'])

    def test_stop_terminates_preview(self):
        self.session.command('preview')
        self.assertEqual(self.session.command('stop')['mode'], 'off')
        self.camera.face_tracking.assert_called_with('stop')

    def test_browser_commands_without_current_owner_cannot_interrupt_tracking(self):
        self.session.command('enable', 'call', require_owner=True)
        before = list(self.sent)
        self.camera.face_tracking.reset_mock()
        for other_session in (None, 'old-call'):
            for action in ('disable', 'stop', 'preview', 'enable'):
                with self.subTest(session=other_session, action=action):
                    with self.assertRaisesRegex(RuntimeError, 'another conversation session'):
                        self.session.command(action, other_session, require_owner=True)
        self.assertEqual(self.sent, before)
        self.assertEqual(self.session.mode, 'tracking')
        self.assertEqual(self.session.session_id, 'call')
        self.assertNotIn('stop', [call.args[0] for call in self.camera.face_tracking.call_args_list])
        self.session.command('disable', 'call', require_owner=True)
        self.assertFalse(self.sent[-1][1]['enabled'])

    def test_internal_cleanup_can_stop_tracking_without_a_browser_owner(self):
        self.session.command('enable', 'call', require_owner=True)
        self.session.command('stop')
        self.assertEqual(self.session.mode, 'off')
        self.assertFalse(self.sent[-1][1]['enabled'])
        self.camera.face_tracking.assert_called_with('stop')

if __name__ == '__main__': unittest.main()
