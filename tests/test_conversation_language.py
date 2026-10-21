"""Language selection at prompt/API/synthesis boundaries, without devices or models."""
import asyncio
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import asr_web
import realtime_voice
import tts_worker
from local_robot_conversation import LocalConversations
from robot_conversation_persona import conversation_language_instruction


class ConversationLanguageTests(unittest.TestCase):
    def test_realtime_initial_system_prompt_uses_selected_language(self):
        for language in ('German', 'English'):
            response = io.BytesIO(b'{"value":"ek_test"}')
            with patch.object(realtime_voice, '_api_key', return_value='test-key'), \
                 patch.object(realtime_voice, 'urlopen', return_value=response) as request:
                self.assertEqual(realtime_voice.create_client_secret('marin', True, language), 'ek_test')
                prompt = json.loads(request.call_args.args[0].data)['session']['instructions']
            self.assertIn(f'Conversation language: {language}', prompt)
            self.assertIn('from the very first greeting', prompt)
            self.assertNotIn('Deutsch ist deine Standardsprache', prompt)
        with self.assertRaises(ValueError):
            conversation_language_instruction('French')

    def test_realtime_token_endpoint_forwards_english(self):
        with patch.object(asr_web.realtime_voice, 'configured', return_value=True), \
             patch.object(asr_web, 'conversation_motion_status', return_value={'active': False}), \
             patch.object(asr_web, 'run_in_threadpool', new_callable=AsyncMock, return_value='ek_test') as mint:
            asyncio.run(asr_web.conversation_realtime_token(
                SimpleNamespace(headers={'x-so101-conversation': 'operator-call'}),
                asr_web.RealtimeVoiceRequest(voiceOnly=True, language='English')))
        mint.assert_awaited_once_with(realtime_voice.create_client_secret, 'marin', True, 'English')

    def test_local_greeting_and_cancel_keep_explicit_language(self):
        for engine, voice, language in [('qwen', 'Dylan', 'English'), ('qwen', 'Ryan', 'German'),
                                        ('piper', 'Amy', 'English'), ('piper', 'Thorsten', 'German')]:
            with self.subTest(engine=engine, voice=voice, language=language):
                generate = Mock(return_value={'content': 'Hello!'})
                sessions = LocalConversations(generate)
                key = sessions.start(None, voice, engine, language)
                sessions.greet(key)
                messages, tools = generate.call_args.args
                self.assertEqual(tools, [])
                self.assertIn(f'Conversation language: {language}', messages[0]['content'])
                self.assertIn(f'Conversation language: {language}', messages[-1]['content'])
                self.assertIn('from the very first greeting', messages[-1]['content'])
                self.assertNotIn('Deutsch ist deine Standardsprache', messages[0]['content'])
                sessions.cancel(key)
                self.assertEqual(sessions.get(key).language, language)
                sessions.feedback(key, {'message': 'Test'})
                self.assertIn(f'Conversation language: {language}', generate.call_args.args[0][-1]['content'])

    def test_local_start_endpoint_stores_language_and_rejects_wrong_piper_voice(self):
        sessions = LocalConversations(Mock())
        with patch.object(asr_web, 'local_conversations', sessions), \
             patch.object(asr_web, 'conversation_motion_status', return_value={'active': False}):
            result = asr_web.local_conversation_start(
                asr_web.LocalConversationStart(engine='qwen', voice='Dylan', language='English'),
                SimpleNamespace(headers={'x-so101-conversation': 'local-conversation'}))
        self.assertEqual(sessions.get(result['sessionId']).language, 'English')
        with self.assertRaises(ValueError):
            sessions.start(None, 'Thorsten', 'piper', 'English')

    def test_qwen_synthesis_receives_english_instead_of_hardcoded_german(self):
        model = Mock()
        model.generate_custom_voice.return_value = ([np.zeros(240, dtype=np.float32)], 24000)
        with patch.object(tts_worker.sf, 'write'):
            tts_worker.speak(model, 'Hello!', 'Dylan', Path('/unused.wav'), 'English')
        self.assertEqual(model.generate_custom_voice.call_args.kwargs['language'], 'English')
        with self.assertRaises(ValueError):
            tts_worker.speak(model, 'Bonjour!', 'Dylan', Path('/unused.wav'), 'French')

    def test_speech_api_forwards_selected_language_to_existing_worker(self):
        def speech(request):
            self.assertEqual(request['language'], 'English')
            Path(request['path']).write_bytes(b'wav-fixture')

        async def inline(function, *args):
            return function(*args)

        with patch.object(asr_web, 'run_in_threadpool', side_effect=inline), \
             patch.object(asr_web.tts_worker, 'request', side_effect=speech), \
             patch.object(Path, 'is_file', return_value=True):
            response = asyncio.run(asr_web.conversation_speak(
                asr_web.SpeakRequest(text='Hello!', language='English', speaker='Dylan')))
        self.assertEqual(response.body, b'wav-fixture')
