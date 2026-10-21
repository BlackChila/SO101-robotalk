"""Explicit Realtime activation and task handover at the HTTP boundary."""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fastapi import HTTPException
from pydantic import ValidationError
import asr_web

class FaceTrackingApiTests(unittest.TestCase):
    def test_explicit_header_required(self):
        with patch.object(asr_web, 'face_tracking_session') as tracking:
            with self.assertRaises(HTTPException) as exc:
                asyncio.run(asr_web.conversation_face_tracking(asr_web.FaceTrackingRequest(action='enable'), SimpleNamespace(headers={})))
        self.assertEqual(exc.exception.status_code, 403)
        tracking.command.assert_not_called()

    def test_voice_only_and_local_cannot_enable(self):
        with patch.object(asr_web, '_realtime_motion_sessions', set()), patch.object(asr_web, 'face_tracking_session') as tracking:
            with self.assertRaises(HTTPException) as exc:
                asyncio.run(asr_web.conversation_face_tracking(asr_web.FaceTrackingRequest(action='enable', sessionId='a'*32), SimpleNamespace(headers={'x-so101-conversation':'operator-face-tracking'})))
        self.assertEqual(exc.exception.status_code, 409)
        tracking.command.assert_not_called()

    def test_preview_is_available_without_robot_session(self):
        with patch.object(asr_web, 'face_tracking_session') as tracking:
            tracking.command.return_value={'mode':'preview'}
            response=asyncio.run(asr_web.conversation_face_tracking(asr_web.FaceTrackingRequest(action='preview'), SimpleNamespace(headers={'x-so101-conversation':'operator-face-tracking'})))
            tracking.command.assert_called_once_with('preview', None, True, 'right', require_owner=True)
        self.assertEqual(response, {'mode':'preview'})

    def test_realtime_enable_passes_current_session_to_coordinator(self):
        with patch.object(asr_web, '_realtime_motion_sessions', {'a'*32}), patch.object(asr_web, 'face_tracking_session') as tracking:
            tracking.command.return_value={'mode':'tracking'}
            asyncio.run(asr_web.conversation_face_tracking(asr_web.FaceTrackingRequest(action='enable',sessionId='a'*32,search=False,searchDirection='left'), SimpleNamespace(headers={'x-so101-conversation':'operator-face-tracking'})))
            tracking.command.assert_called_once_with('enable','a'*32,False,'left',require_owner=True)

    def test_invalid_direction_is_rejected(self):
        with self.assertRaises(ValidationError):
            asr_web.FaceTrackingRequest(action='enable', searchDirection='backward')

    def test_browser_cannot_inject_face_coordinates(self):
        with self.assertRaises(ValidationError):
            asr_web.FaceTrackingRequest(action='enable', observation={'x':1,'y':1})
        with self.assertRaises(ValidationError):
            asr_web.FaceTrackingRequest(action='enable',mode='local')

    def test_task_request_disables_gaze_before_starting_policy(self):
        sid='c'*32
        with patch.object(asr_web,'conversation_motion_status',return_value={'sessionId':sid,'state':'holding'}), patch.object(asr_web,'face_tracking_session') as tracking, patch.object(asr_web,'_conversation_task_calls',{}):
            tracking.disable.side_effect=RuntimeError('hold not acknowledged')
            with self.assertRaises(HTTPException) as exc:
                asr_web.conversation_task_start(asr_web.ConversationTaskRequest(sessionId=sid,instruction='pick up object',callId='call'), SimpleNamespace(headers={'x-so101-conversation':'realtime-tool'}))
            tracking.disable.assert_called_once()
            self.assertEqual(exc.exception.status_code,409)

if __name__=='__main__':unittest.main()
