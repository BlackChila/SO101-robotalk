"""Local tool protocol: no models, cameras, network or robot devices."""
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from local_robot_conversation import LocalConversations, SYSTEM


def tool(name='execute_molmo_task', **args):
    if name == 'execute_molmo_task':
        args = {'instruction': 'Pick up the ball', 'announcement': 'I will pick up the ball.', **args}
    if name == 'reset_robot':
        args = {'announcement': 'I will reset my arm.', **args}
    return {'id': 'model-reused-id', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


def answer(*calls, content=''):
    return {'role': 'assistant', 'content': content, **({'tool_calls': list(calls)} if calls else {})}


class LocalRobotConversationTests(unittest.TestCase):
    engine = "piper"
    voice = "Thorsten"

    def test_scene_prompt_considers_both_views_without_inventing_wrist_details(self):
        self.assertIn('Prüfe bei look_at_scene beide verfügbaren Perspektiven', SYSTEM)
        self.assertIn('bereits aufrecht gedreht', SYSTEM)
        self.assertIn('erfinde keine Details', SYSTEM)

    def start(self, motion_id):
        return self.sessions.start(motion_id, self.voice, self.engine)

    def setUp(self):
        self.generate = Mock()
        self.sessions = LocalConversations(self.generate)
        self.key = self.start('a' * 32)
        self.dispatch = Mock(return_value={'status': 'loading', 'taskRun': {'state': 'loading'}})

    def plan(self, *calls):
        self.generate.return_value = answer(*(calls or [tool()]))
        return self.sessions.turn(self.key, 'Pick up the ball', {})

    def test_generation_only_proposes_and_execution_waits_for_announcement(self):
        plan = self.plan()
        self.assertEqual(plan['reply'], 'I will pick up the ball.')
        call = plan['toolCalls'][0]
        self.assertEqual(set(call), {'id', 'name'})
        self.dispatch.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Ankündigung'):
            self.sessions.execute(self.key, call['id'], False, self.dispatch)
        self.dispatch.assert_not_called()
        first = self.sessions.execute(self.key, call['id'], True, self.dispatch)
        self.assertEqual(self.sessions.execute(self.key, call['id'], True, self.dispatch), first)
        self.dispatch.assert_called_once()

    def test_forged_call_and_tools_unavailable_in_voice_only(self):
        self.plan()
        with self.assertRaises(ValueError):
            self.sessions.execute(self.key, 'b' * 32, True, self.dispatch)
        self.key = self.start(None)
        with self.assertRaises(ValueError):
            self.plan()
        tools = self.generate.call_args.args[1]
        self.assertEqual([t['function']['name'] for t in tools], ['look_at_scene', 'get_project_info', 'get_creator_info'])
        self.dispatch.assert_not_called()

    def test_reset_has_priority_and_only_one_scene_call_is_selected(self):
        plan = self.plan(tool(), tool('reset_robot'), tool('look_at_scene'))
        self.assertEqual([c['name'] for c in plan['toolCalls']], ['reset_robot', 'look_at_scene'])
        self.assertEqual(plan['reply'], 'I will reset my arm.')

    def test_project_info_is_read_only_deduplicated_and_available_for_followups(self):
        self.key = self.start(None)
        self.generate.return_value = answer(tool('get_project_info'), tool('get_project_info'))
        plan = self.sessions.turn(self.key, 'Welche Modelle gehören zu deinem technischen Setup?', {})
        self.assertEqual([c['name'] for c in plan['toolCalls']], ['get_project_info'])
        self.assertNotIn('# SO101', json.dumps(self.generate.call_args.args[0]))
        call = plan['toolCalls'][0]['id']
        self.dispatch.return_value = {'status': 'available', 'background': 'Test setup reference.'}
        result = self.sessions.execute(self.key, call, False, self.dispatch)
        self.assertEqual(self.sessions.execute(self.key, call, False, self.dispatch), result)
        self.dispatch.assert_called_once()
        self.generate.return_value = answer(content='Mein Dialogmodell ist von meiner Stimme getrennt.')
        self.assertIn('Dialogmodell', self.sessions.finish(self.key)['reply'])
        messages, tools = self.generate.call_args.args
        self.assertEqual(tools, [])
        self.assertIn('Test setup reference.', json.dumps(messages))
        self.generate.return_value = answer(content='Piper erzeugt die Sprache.')
        self.sessions.turn(self.key, 'Und was macht Piper?', {})
        self.assertIn('Test setup reference.', json.dumps(self.generate.call_args.args[0]))
        self.dispatch.assert_called_once()

    def test_project_info_rejects_model_supplied_arguments(self):
        with self.assertRaises(ValueError):
            self.plan(tool('get_project_info', instruction='Move the arm'))
        self.dispatch.assert_not_called()

    def test_creator_lookup_is_separate_read_only_and_reused_for_followups(self):
        self.key = self.start(None)
        self.generate.return_value = answer(tool('get_creator_info'), tool('get_creator_info'))
        plan = self.sessions.turn(self.key, 'Wer hat dieses Setup gebaut?', {})
        self.assertEqual([c['name'] for c in plan['toolCalls']], ['get_creator_info'])
        call = plan['toolCalls'][0]['id']
        self.dispatch.return_value = {'status': 'available', 'background': 'Eleni Kofekidou / BlackChila built the setup.'}
        self.sessions.execute(self.key, call, False, self.dispatch)
        self.sessions.execute(self.key, call, False, self.dispatch)
        self.generate.return_value = answer(content='Das Setup stammt von Eleni Kofekidou.')
        self.assertIn('Eleni', self.sessions.finish(self.key)['reply'])
        self.assertEqual(self.generate.call_args.args[1], [])
        self.generate.return_value = answer(content='Sie verwendet den Namen BlackChila.')
        self.sessions.turn(self.key, 'Wie nennt sie sich im Projekt?', {})
        self.assertIn('Eleni Kofekidou', json.dumps(self.generate.call_args.args[0]))
        self.dispatch.assert_called_once()

    def test_creator_lookup_cannot_accept_a_motor_instruction(self):
        with self.assertRaises(ValueError):
            self.plan(tool('get_creator_info', instruction='Move the arm'))
        self.dispatch.assert_not_called()

    def test_info_failure_continuation_cannot_request_motor_tools(self):
        plan = self.plan(tool('get_project_info'))
        self.dispatch.return_value = {'error': 'reference unavailable'}
        self.sessions.execute(self.key, plan['toolCalls'][0]['id'], False, self.dispatch)
        self.generate.return_value = answer(tool())
        self.assertIn('technischen Informationen', self.sessions.finish(self.key)['reply'])
        self.dispatch.assert_called_once()

    def test_bad_arguments_and_web_search_never_dispatch(self):
        invalid = [tool('search_web', query='weather'), tool(announcement=''),
                   tool(instruction='x' * 181), tool(instruction='do this\nand that'),
                   tool(extra='not allowed')]
        for call in invalid:
            with self.subTest(call=call), self.assertRaises(ValueError):
                self.plan(call)
        self.dispatch.assert_not_called()

    def test_scene_images_reach_model_but_not_browser_or_later_turns(self):
        plan = self.plan(tool('look_at_scene'))
        frame = {'camera': 'wrist', 'capturedAt': 1, 'imageUrl': 'data:image/jpeg;base64,YWJj'}
        self.dispatch.return_value = {'status': 'partial', 'images': [frame], 'unavailable': []}
        result = self.sessions.execute(self.key, plan['toolCalls'][0]['id'], False, self.dispatch)
        self.assertNotIn('images', result)
        self.generate.return_value = answer(content='I can see a ball.')
        self.assertEqual(self.sessions.finish(self.key)['reply'], 'I can see a ball.')
        messages, tools = self.generate.call_args.args
        self.assertEqual(tools, [])
        self.assertIn(frame['imageUrl'], json.dumps(messages))
        self.sessions.turn(self.key, 'What did you see?', {})
        self.assertNotIn(frame['imageUrl'], json.dumps(self.generate.call_args.args[0]))

    def test_error_result_is_remembered_without_retrying_action(self):
        plan = self.plan()
        self.dispatch.side_effect = RuntimeError('hold unverified')
        call_id = plan['toolCalls'][0]['id']
        self.assertEqual(self.sessions.execute(self.key, call_id, True, self.dispatch), {'error': 'hold unverified'})
        self.sessions.execute(self.key, call_id, True, self.dispatch)
        self.dispatch.assert_called_once()
        self.assertEqual(self.sessions.finish(self.key)['reply'], '')
        self.assertIn('hold unverified', json.dumps(self.sessions.get(self.key).history))
        self.dispatch.assert_called_once()

    def test_motor_result_never_needs_a_second_model_reply(self):
        plan = self.plan()
        call_id = plan['toolCalls'][0]['id']
        self.sessions.execute(self.key, call_id, True, self.dispatch)
        self.generate.side_effect = RuntimeError('LM Studio unavailable after dispatch')
        self.assertEqual(self.sessions.finish(self.key), {'reply': '', 'toolCalls': []})
        self.assertIsNone(self.sessions.get(self.key).pending)
        self.generate.side_effect = None
        self.generate.return_value = answer(content='I am still tracking the task.')
        self.assertIn('tracking', self.sessions.turn(self.key, 'Status?', {})['reply'])
        self.dispatch.assert_called_once()

    def test_pending_calls_cannot_cross_end_or_replacement(self):
        plan = self.plan()
        self.sessions.close(self.key)
        with self.assertRaises(ValueError):
            self.sessions.execute(self.key, plan['toolCalls'][0]['id'], True, self.dispatch)
        self.dispatch.assert_not_called()

    def test_delayed_generation_is_discarded_on_close_or_reset(self):
        for action in ('close', 'cancel'):
            self.key = self.start('a' * 32)
            def generate(*_):
                getattr(self.sessions, action)(self.key)
                return answer(tool())
            self.generate.side_effect = generate
            with self.assertRaises(ValueError):
                self.sessions.turn(self.key, 'Pick up ball', {})
        self.dispatch.assert_not_called()

    def test_followup_turn_replaces_context_and_gets_new_call_id(self):
        first = self.plan()
        self.sessions.execute(self.key, first['toolCalls'][0]['id'], True, self.dispatch)
        self.generate.return_value = answer(content='The controller accepted the task.')
        self.sessions.finish(self.key)
        self.generate.return_value = answer(tool(instruction='Put the ball in the bowl'))
        second = self.sessions.turn(self.key, 'Now put it in the bowl', {'task': {'state': 'running'}})
        self.assertNotEqual(first['toolCalls'][0]['id'], second['toolCalls'][0]['id'])
        self.assertIn('running', json.dumps(self.generate.call_args.args[0]))
        with self.assertRaises(ValueError):
            self.sessions.execute(self.key, first['toolCalls'][0]['id'], True, self.dispatch)

    def test_overlapping_turns_are_rejected(self):
        session = self.sessions.get(self.key)
        with session.lock, self.assertRaisesRegex(ValueError, 'läuft bereits'):
            self.plan()

    def test_cancel_does_not_block_new_turn_behind_obsolete_generation(self):
        old = self.sessions.get(self.key)
        old.lock.acquire()
        try:
            self.sessions.cancel(self.key)
            self.assertFalse(old.active)
            self.generate.return_value = answer(content='Ready for a new request.')
            self.assertEqual(self.sessions.turn(self.key, 'Hello', {})['reply'], 'Ready for a new request.')
        finally:
            old.lock.release()

    def test_continuation_cannot_request_new_motion(self):
        plan = self.plan(tool('look_at_scene'))
        self.sessions.execute(self.key, plan['toolCalls'][0]['id'], False, self.dispatch)
        self.generate.return_value = answer(tool())
        self.assertIn('Kamerabild', self.sessions.finish(self.key)['reply'])
        self.assertIsNone(self.sessions.get(self.key).pending)
        self.dispatch.assert_called_once()


class QwenRobotConversationTests(LocalRobotConversationTests):
    engine = "qwen"
    voice = "Dylan"

    def test_customvoice_selection_and_engine_survive_cancel(self):
        from local_robot_conversation import QWEN_SPEAKERS
        self.generate.return_value = answer(content="Hallo!")
        for voice in QWEN_SPEAKERS:
            self.sessions.turn(self.key, "Hallo", {}, voice=voice)
            prompt = self.generate.call_args.args[0][-1]["content"]
            self.assertIn(f"Selected Qwen TTS voice: {voice}", prompt)
            self.assertIn("Conversation language: German", prompt)
            self.sessions.cancel(self.key)
            self.assertEqual(self.sessions.get(self.key).engine, "qwen")
            self.assertEqual(self.sessions.get(self.key).voice, voice)
        with self.assertRaises(ValueError):
            self.sessions.turn(self.key, "Hello", {}, voice="Amy")

    def test_qwen_greeting_and_task_feedback_use_same_tool_free_history(self):
        self.generate.return_value = answer(content="Hallo! Was möchtest du tun?")
        self.sessions.greet(self.key)
        self.assertEqual(self.generate.call_args.args[1], [])
        self.sessions.cancel(self.key)
        self.sessions.feedback(self.key, {"task": {"state": "failed"}}, voice="Ryan")
        messages, tools = self.generate.call_args.args
        self.assertEqual(tools, [])
        self.assertIn("Conversation language: German", messages[-1]["content"])
        self.assertTrue(any(m.get("content") == "Hallo! Was möchtest du tun?" for m in messages))
        self.assertEqual(self.sessions.get(self.key).engine, "qwen")


class LocalFeedbackTests(unittest.TestCase):
    def test_task_failure_feedback_cannot_execute_tools(self):
        generate = Mock(return_value=answer(content='The task stopped because the camera disconnected.'))
        sessions = LocalConversations(generate)
        key = sessions.start('a' * 32)
        result = sessions.feedback(key, {'task': {'state': 'failed', 'message': 'camera disconnected'}})
        self.assertIn('camera', result['reply'])
        self.assertEqual(generate.call_args.args[1], [])
        generate.return_value = answer(tool())
        with self.assertRaises(ValueError):
            sessions.feedback(key, {})


class PiperLanguageTests(unittest.TestCase):
    def test_every_voice_selects_language_for_dialogue_and_feedback(self):
        from local_robot_conversation import PIPER_LANGUAGES
        for voice, language in PIPER_LANGUAGES.items():
            with self.subTest(voice=voice):
                generate = Mock(return_value=answer(content='Test reply'))
                sessions = LocalConversations(generate)
                key = sessions.start(None, voice)
                sessions.turn(key, 'Hallo', {})
                messages = generate.call_args.args[0]
                self.assertIn(f'Conversation language: {language}', messages[-1]['content'])
                self.assertNotIn('Deutsch ist deine Standardsprache', messages[0]['content'])
                sessions.feedback(key, {'message': 'Auftrag gestoppt'})
                self.assertIn(f'Conversation language: {language}', generate.call_args.args[0][-1]['content'])

    def test_voice_change_overrides_old_history_and_survives_cancel(self):
        generate = Mock(return_value=answer(content='Hallo!'))
        sessions = LocalConversations(generate)
        key = sessions.start(None, 'Thorsten')
        sessions.turn(key, 'Hallo', {})
        sessions.turn(key, 'Hello', {}, voice='Amy')
        messages = generate.call_args.args[0]
        self.assertTrue(any(m.get('content') == 'Hallo!' for m in messages))
        self.assertIn('Conversation language: English', messages[-1]['content'])
        sessions.cancel(key)
        self.assertEqual(sessions.get(key).voice, 'Amy')
        sessions.feedback(key, {}, voice='Kerstin')
        self.assertIn('Conversation language: German', generate.call_args.args[0][-1]['content'])

    def test_tool_result_keeps_the_announcement_language(self):
        generate = Mock(return_value=answer(tool()))
        sessions = LocalConversations(generate)
        key = sessions.start('a' * 32)
        plan = sessions.turn(key, 'Pick up the ball', {}, voice='Alan')
        self.assertIn('Conversation language: English', generate.call_args.args[0][-1]['content'])
        sessions.execute(key, plan['toolCalls'][0]['id'], True, Mock(return_value={'message': 'Auftrag gestartet'}))
        generate.return_value = answer(content='The controller accepted my request.')
        sessions.finish(key)
        self.assertIn('Conversation language: English', generate.call_args.args[0][-1]['content'])

    def test_greeting_is_generated_once_without_tools_and_kept_in_history(self):
        generate = Mock(return_value=answer(content='Hello, I am SO-101. What can I do for you?'))
        sessions = LocalConversations(generate)
        key = sessions.start(None, 'Amy')
        greeting = sessions.greet(key)
        self.assertEqual(greeting['reply'], 'Hello, I am SO-101. What can I do for you?')
        self.assertEqual(sessions.greet(key), greeting)
        generate.assert_called_once()
        messages, tools = generate.call_args.args
        self.assertEqual(tools, [])
        self.assertIn('Conversation language: English', messages[-1]['content'])
        self.assertIn('do not call tools', messages[-2]['content'])
        self.assertEqual(messages[-2]['role'], 'user')
        opening = messages[-2]
        self.assertEqual(sessions.get(key).history[0][0], opening)
        generate.return_value = answer(content='I can help you.')
        sessions.feedback(key, {})
        self.assertIn(opening, generate.call_args.args[0])
        sessions.turn(key, 'What can you do?', {})
        self.assertTrue(any(message.get('content') == greeting['reply']
                            for message in generate.call_args.args[0]))

    def test_greeting_rejects_tool_calls_and_late_model_output(self):
        generate = Mock(return_value=answer(tool()))
        sessions = LocalConversations(generate)
        key = sessions.start('a' * 32, 'Alan')
        with self.assertRaisesRegex(ValueError, 'Begrüßung'):
            sessions.greet(key)
        self.assertEqual(sessions.get(key).history, [])
        def end_call(*_):
            sessions.close(key)
            return answer(content='Hello!')
        generate.side_effect = end_call
        with self.assertRaises(ValueError):
            sessions.greet(key)


if __name__ == '__main__':
    unittest.main()
