"""Exercise local HTTP boundaries with simulated dialogue and controllers."""
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import asr_web
from local_robot_conversation import LocalConversations

HEADERS = {'x-so101-conversation': 'local-conversation'}
SID = 'a' * 32


def tool_message(name='execute_molmo_task'):
    args = {} if name in {'look_at_scene', 'get_project_info', 'get_creator_info'} else {'announcement': 'I will reset my arm.'}
    if name == 'execute_molmo_task':
        args = {'announcement': 'I will pick up the ball.', 'instruction': 'Pick up the ball'}
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}


class LocalConversationApiTests(unittest.TestCase):
    engine = "piper"
    voice = "Thorsten"

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.generate = Mock(return_value=tool_message())
        self.local = LocalConversations(self.generate)
        self.motion = {'sessionId': SID, 'active': True, 'state': 'holding', 'returnRequested': False}
        self.stack.enter_context(patch.object(asr_web, 'local_conversations', self.local))
        self.stack.enter_context(patch.object(asr_web, 'conversation_motion_status', side_effect=lambda: dict(self.motion)))
        self.stack.enter_context(patch.object(asr_web, 'task_status', return_value=None))
        self.stack.enter_context(patch.object(asr_web, '_realtime_motion_sessions', set()))
        self.tracking = self.stack.enter_context(patch.object(asr_web, 'face_tracking_session'))
        self.real_start_task = asr_web.start_conversation_task
        self.task = self.stack.enter_context(patch.object(asr_web, 'start_conversation_task', side_effect=self.accept))
        self.reset = self.stack.enter_context(patch.object(asr_web, 'reset_conversation_robot', side_effect=self.accept))
        self.camera = self.stack.enter_context(patch.object(asr_web, 'camera_session'))
        self.camera.scene_snapshot.return_value = {'status': 'unavailable', 'images': [], 'unavailable': []}

    def accept(self, request, **kwargs):
        kwargs['authorize']()
        return {'status': 'accepted'}

    def request(self, path, payload=None, method='POST', headers=HEADERS):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=asr_web.app), base_url='http://testserver') as client:
                return await client.request(method, '/api/conversation/local/' + path, json=payload, headers=headers)
        return asyncio.run(run())

    def start(self, motion_id=SID):
        response = self.request('start', {'motionSessionId': motion_id, 'engine': self.engine, 'voice': self.voice})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['sessionId']

    def plan(self, key):
        response = self.request(key + '/turn', {'text': 'Pick up the ball'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['toolCalls'][0]['id']

    def test_start_requires_header_and_current_active_held_non_realtime_arm(self):
        self.assertEqual(self.request('start', {'motionSessionId': SID}, headers={}).status_code, 403)
        self.motion['state'] = 'intro'
        self.assertEqual(self.request('start', {'motionSessionId': SID}).status_code, 409)
        self.motion['state'] = 'holding'
        asr_web._realtime_motion_sessions.add(SID)
        self.assertEqual(self.request('start', {'motionSessionId': SID}).status_code, 409)
        self.task.assert_not_called()

    def test_turn_does_not_move_and_tool_reuses_validated_backend_operation(self):
        key = self.start()
        call = self.plan(key)
        self.task.assert_not_called()
        response = self.request(key + '/tool', {'callId': call, 'announced': True, 'instruction': 'injected'})
        self.assertEqual(response.status_code, 422)
        response = self.request(key + '/tool', {'callId': call, 'announced': False})
        self.assertEqual(response.status_code, 409)
        response = self.request(key + '/tool', {'callId': call, 'announced': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.task.call_args.args[0].instruction, 'Pick up the ball')
        self.assertEqual(self.task.call_args.args[0].sessionId, SID)
        self.request(key + '/tool', {'callId': call, 'announced': True})
        self.task.assert_called_once()

    def test_accepted_motor_task_needs_no_second_model_answer(self):
        key = self.start()
        call = self.plan(key)
        self.assertEqual(self.request(key + '/tool', {'callId': call, 'announced': True}).status_code, 200)
        self.generate.side_effect = RuntimeError('LM Studio response unavailable')
        response = self.request(key + '/continue')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'reply': '', 'toolCalls': []})
        self.task.assert_called_once()
        self.assertIsNone(self.local.get(key).pending)

    def test_closed_or_cancelled_session_cannot_dispatch(self):
        for method, suffix in [('DELETE', ''), ('POST', '/cancel')]:
            key = self.start()
            call = self.plan(key)
            self.assertEqual(self.request(key + suffix, method=method).status_code, 200)
            self.assertEqual(self.request(key + '/tool', {'callId': call, 'announced': True}).status_code, 409)
        self.task.assert_not_called()

    def test_live_owner_change_blocks_already_generated_call(self):
        key = self.start()
        call = self.plan(key)
        self.motion['sessionId'] = 'b' * 32
        response = self.request(key + '/tool', {'callId': call, 'announced': True})
        self.assertIn('error', response.json())
        self.task.assert_not_called()

    def test_reset_uses_shared_reset_service(self):
        self.generate.return_value = tool_message('reset_robot')
        key = self.start()
        call = self.plan(key)
        response = self.request(key + '/tool', {'callId': call, 'announced': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.reset.call_args.kwargs['origin'], 'local-tool')
        self.task.assert_not_called()

    def test_voice_only_can_observe_and_answer_without_motion(self):
        self.motion.update(active=False, state='idle', sessionId=None)
        self.generate.return_value = tool_message('look_at_scene')
        key = self.start(None)
        call = self.plan(key)
        self.assertEqual(self.request(key + '/tool', {'callId': call}).json()['status'], 'unavailable')
        self.generate.return_value = {'role': 'assistant', 'content': 'My view is unavailable.'}
        response = self.request(key + '/continue')
        self.assertEqual(response.json()['reply'], 'My view is unavailable.')
        self.camera.scene_snapshot.assert_called_once()
        self.task.assert_not_called()
        self.reset.assert_not_called()

    def test_piper_session_enables_existing_tracking_and_close_revokes_it(self):
        key = self.start()
        request = asr_web.FaceTrackingRequest(action='enable', sessionId=SID)
        browser = SimpleNamespace(headers={'x-so101-conversation': 'operator-face-tracking'})
        asyncio.run(asr_web.conversation_face_tracking(request, browser))
        self.tracking.command.assert_called_once_with('enable', SID, True, 'right', require_owner=True)
        self.request(key, method='DELETE')
        with self.assertRaises(asr_web.HTTPException):
            asyncio.run(asr_web.conversation_face_tracking(request, browser))

    def test_voice_only_setup_info_uses_session_engine_without_touching_hardware(self):
        self.motion.update(active=False, state='idle', sessionId=None)
        self.generate.return_value = tool_message('get_project_info')
        key = self.start(None)
        call = self.plan(key)
        with patch.object(asr_web.conversation_llm, 'MODEL', 'custom/dialogue'), \
             patch.object(asr_web.conversation_llm, 'model_status') as model_status, \
             patch.object(asr_web, 'require_local_motion') as require_motion:
            response = self.request(key + '/tool', {'callId': call})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()['activeConversation']
            self.assertEqual(result['mode'], 'Lokal · Piper' if self.engine == 'piper' else 'Lokal · Qwen')
            self.assertEqual(result['voice'], self.voice)
            self.assertEqual(result['dialogue']['model'], 'custom/dialogue')
            self.assertIsNone(result['dialogue']['parametersBillions'])
            self.assertEqual(self.request(key + '/tool', {'callId': call}).json(), response.json())
            model_status.assert_not_called()
            require_motion.assert_not_called()
        self.generate.return_value = {'role': 'assistant', 'content': 'Die Modelle haben verschiedene Aufgaben.'}
        self.assertEqual(self.request(key + '/continue').json()['reply'], 'Die Modelle haben verschiedene Aufgaben.')
        self.assertEqual(self.camera.mock_calls, [])
        self.task.assert_not_called()
        self.reset.assert_not_called()

    def test_cancel_during_gaze_handover_prevents_policy_dispatch(self):
        key = self.start()
        call_id = self.plan(key)
        self.task.side_effect = self.real_start_task
        self.tracking.disable.side_effect = lambda _: self.local.cancel(key)
        with patch.object(asr_web, '_conversation_task_calls', {}), \
             patch.object(asr_web.threading, 'Thread') as worker:
            result = self.local.execute(key, call_id, True, asr_web.dispatch_local_tool)
            self.assertIn('error', result)
            worker.assert_not_called()

    def test_voice_only_creator_lookup_does_not_require_a_motion_owner(self):
        self.motion.update(active=False, state='idle', sessionId=None)
        self.generate.return_value = tool_message('get_creator_info')
        key = self.start(None)
        plan = self.request(key + '/turn', {'text': 'Who built this project?'})
        self.assertEqual(plan.status_code, 200, plan.text)
        call = plan.json()['toolCalls'][0]['id']
        with patch.object(asr_web, 'require_local_motion') as require_motion:
            response = self.request(key + '/tool', {'callId': call})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('Eleni Kofekidou', response.json()['background'])
            require_motion.assert_not_called()
        self.generate.return_value = {'content': 'The RoboTalk setup was built by Eleni Kofekidou.'}
        self.assertIn('Eleni', self.request(key + '/continue').json()['reply'])
        self.assertEqual(self.camera.mock_calls, [])
        self.task.assert_not_called()
        self.reset.assert_not_called()

    def test_voice_selection_reaches_turn_and_status_prompts(self):
        self.generate.return_value = {'role': 'assistant', 'content': 'Hello.'}
        key = self.request('start', {'motionSessionId': SID, 'voice': 'Amy'}).json()['sessionId']
        self.assertEqual(self.local.get(key).voice, 'Amy')
        response = self.request(key + '/turn', {'text': 'Hello', 'voice': 'Alan'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('Selected Piper voice: Alan', self.generate.call_args.args[0][-1]['content'])
        response = self.request(key + '/feedback', {'voice': 'Kerstin'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('Conversation language: German', self.generate.call_args.args[0][-1]['content'])
        self.assertEqual(self.request(key + '/turn', {'text': 'Hello', 'voice': 'unknown'}).status_code, 422)

    def test_greeting_uses_selected_voice_and_cannot_dispatch_tools(self):
        self.generate.return_value = {'role': 'assistant', 'content': 'Hello, I am SO-101. What can I do for you?'}
        key = self.request('start', {'motionSessionId': SID, 'voice': 'Amy'}).json()['sessionId']
        response = self.request(key + '/greet', {'voice': 'Amy'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('Hello', response.json()['reply'])
        self.assertEqual(self.generate.call_args.args[1], [])
        self.assertEqual(self.request(key + '/greet', {'voice': 'Amy'}).json(), response.json())
        self.generate.assert_called_once()
        self.task.assert_not_called()
        self.reset.assert_not_called()

    def test_qwen_opening_endpoint_returns_generated_reply_and_history_id(self):
        async def request(headers):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=asr_web.app), base_url='http://testserver') as client:
                return await client.post('/api/conversation/greet', headers=headers)
        with patch.object(asr_web.conversation_llm, 'greet', return_value={
                'reply': 'Hallo! Was möchtest du tun?', 'responseId': 'resp_greeting'}) as greet:
            self.assertEqual(asyncio.run(request({})).status_code, 403)
            greet.assert_not_called()
            response = asyncio.run(request(HEADERS))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['responseId'], 'resp_greeting')
            greet.assert_called_once_with()
        self.task.assert_not_called()
        self.reset.assert_not_called()

    def test_preparation_keeps_shared_cameras_and_warm_molmo(self):
        self.camera.model_id = 'conversation'
        self.motion['active'] = False
        with patch.object(asr_web, 'policy_session', SimpleNamespace(model_id='molmoact2')), \
             patch.object(asr_web, 'piper_voice_ready', return_value=True), \
             patch.object(asr_web, 'follower_port_available', return_value=False), \
             patch.object(asr_web.conversation_llm, 'ensure_model_loaded', return_value={'ready': True}), \
             patch.object(asr_web, 'piper_worker') as piper:
            result = asyncio.run(asr_web.conversation_prepare(asr_web.PrepareConversationRequest(mode='piper')))
            self.assertTrue(result['dialogueReady'])
            piper.ensure_ready.assert_called_once()
        self.camera.stop.assert_not_called()
        self.task.assert_not_called()


class QwenConversationApiTests(LocalConversationApiTests):
    engine = "qwen"
    voice = "Dylan"

    def test_qwen_voice_and_provider_are_validated_before_replacing_session(self):
        key = self.start()
        self.assertEqual(self.local.get(key).engine, "qwen")
        self.assertEqual(self.request('start', {'motionSessionId': SID, 'engine': 'qwen', 'voice': 'Amy'}).status_code, 422)
        self.assertEqual(self.request('start', {'motionSessionId': SID, 'engine': 'piper', 'voice': 'Dylan'}).status_code, 422)
        self.assertTrue(self.local.get(key).active)
        self.generate.return_value = {'content': 'Hallo!'}
        self.assertEqual(self.request(key + '/greet', {'voice': 'Ryan'}).status_code, 200)
        self.assertIn('Selected Qwen TTS voice: Ryan', self.generate.call_args.args[0][-1]['content'])
        self.assertIn('Conversation language: German', self.generate.call_args.args[0][-1]['content'])
        self.assertEqual(self.request(key + '/turn', {'text': 'Hallo', 'voice': 'Amy'}).status_code, 409)

    def test_qwen_preparation_reuses_cameras_and_idle_molmo_but_blocks_active_owners(self):
        self.camera.model_id = 'conversation'
        self.motion['active'] = False
        with patch.object(asr_web, 'policy_session', SimpleNamespace(model_id='molmoact2')), \
             patch.object(asr_web, 'follower_port_available', return_value=False), \
             patch.object(asr_web, 'TTS_PYTHON') as python, \
             patch.object(asr_web, 'TTS_MANIFEST') as manifest, \
             patch.object(asr_web.conversation_llm, 'ensure_model_loaded', return_value={'ready': True}), \
             patch.object(asr_web, 'tts_worker') as tts, \
             patch.object(asr_web, 'piper_worker') as piper:
            python.is_file.return_value = manifest.is_file.return_value = True
            options = asr_web.PrepareConversationRequest(mode='local')
            self.assertTrue(asyncio.run(asr_web.conversation_prepare(options))['ttsReady'])
            tts.ensure_ready.assert_called_once()
            piper.ensure_ready.assert_not_called()
            self.motion['active'] = True
            with self.assertRaises(asr_web.HTTPException) as blocked:
                asyncio.run(asr_web.conversation_prepare(options))
            self.assertEqual(blocked.exception.status_code, 409)
            self.motion['active'] = False
            with patch.object(asr_web, 'task_status', return_value={'state': 'running'}):
                with self.assertRaises(asr_web.HTTPException):
                    asyncio.run(asr_web.conversation_prepare(options))
            tts.ensure_ready.assert_called_once()
        self.camera.stop.assert_not_called()
        self.task.assert_not_called()

    def test_qwen_synthesis_uses_selected_customvoice_worker(self):
        def synthesize(payload):
            Path(payload['path']).write_bytes(b'RIFF-test-wave')
        with patch.object(asr_web, 'TTS_PYTHON') as python, \
             patch.object(asr_web, 'TTS_MANIFEST') as manifest, \
             patch.object(asr_web, 'tts_worker') as tts, \
             patch.object(asr_web, 'piper_worker') as piper:
            python.is_file.return_value = manifest.is_file.return_value = True
            tts.request.side_effect = synthesize
            result = asyncio.run(asr_web.conversation_speak(asr_web.SpeakRequest(
                text='Ich schaue mich um.', engine='qwen', speaker='Dylan')))
            self.assertEqual(result.body, b'RIFF-test-wave')
            self.assertEqual(tts.request.call_args.args[0]['speaker'], 'Dylan')
            piper.request.assert_not_called()
        self.task.assert_not_called()


if __name__ == '__main__':
    unittest.main()
