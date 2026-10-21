"""LM Studio conversation contract without starting a model or robot."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lm_studio_conversation as dialogue  # noqa: E402


class LmStudioConversationTests(unittest.TestCase):
    def test_status_accepts_the_loaded_model_quantization(self) -> None:
        model = {"key": dialogue.MODEL, "quantization": {"name": "Q4_K_M"},
                 "loaded_instances": []}
        with patch.object(dialogue, "_request", return_value={"models": [model]}):
            self.assertFalse(dialogue.model_status()["ready"])
            model["loaded_instances"] = [{"id": dialogue.MODEL}]
            self.assertTrue(dialogue.model_status()["ready"])
            model["quantization"]["name"] = "Q8_0"
            self.assertTrue(dialogue.model_status()["ready"])

    def test_reply_uses_lm_studio_state_without_replaying_history(self) -> None:
        with patch.object(dialogue, "_request", return_value={
                 "output": [{"type": "reasoning", "content": "private"},
                            {"type": "message", "content": "Hallo!"}],
                 "response_id": "resp_next"}) as request:
            self.assertEqual(dialogue.reply("Guten Morgen", "resp_previous"), {
                "reply": "Hallo!", "responseId": "resp_next"})
            path, body = request.call_args.args[:2]
            self.assertEqual(path, "/api/v1/chat")
            self.assertEqual(body["previous_response_id"], "resp_previous")
            self.assertEqual(body["reasoning"], "off")
            self.assertTrue(body["store"])
            self.assertIn("Sprich als der Roboter in der Ich-Form", body["system_prompt"])
            self.assertIn("Steuerungsmodus", body["system_prompt"])
            self.assertNotIn("William", body["system_prompt"])
            self.assertNotIn("history", body)

    def test_qwen_greeting_sends_input_and_keeps_continuation_id(self) -> None:
        with patch.object(dialogue, '_request', return_value={
                'output': [{'type': 'message', 'content': 'Hallo! Was kann ich für dich tun?'}],
                'response_id': 'resp_opening'}) as request:
            result = dialogue.greet()
        self.assertEqual(result['responseId'], 'resp_opening')
        payload = request.call_args.args[1]
        self.assertIn('Begin this conversation', payload['input'])
        self.assertIn('Use German', payload['input'])
        self.assertNotIn('previous_response_id', payload)
        self.assertTrue(payload['store'])

    def test_prepare_loads_only_installed_unloaded_dialogue_model(self) -> None:
        unloaded = {"key": dialogue.MODEL, "quantization": {"name": "Q4_K_M"},
                    "loaded_instances": []}
        loaded = {**unloaded, "loaded_instances": [{"id": dialogue.MODEL}]}
        with patch.object(dialogue, "_request", side_effect=[
                {"models": [unloaded]}, {"status": "loaded"}, {"models": [loaded]}]) as request:
            self.assertTrue(dialogue.ensure_model_loaded()["ready"])
            self.assertEqual(request.call_args_list[1].args,
                             ("/api/v1/models/load", {"model": dialogue.MODEL}))
        with patch.object(dialogue, "_request", return_value={"models": [loaded]}) as request:
            self.assertTrue(dialogue.ensure_model_loaded()["ready"])
            self.assertEqual(request.call_count, 2)


class LocalToolAdapterTests(unittest.TestCase):
    def test_tool_adapter_uses_chat_completions_and_preserves_structured_calls(self):
        calls = [{'id': 'call', 'type': 'function', 'function': {'name': 'look_at_scene', 'arguments': '{}'}}]
        with patch.object(dialogue, '_request', return_value={'choices': [{
                'finish_reason': 'tool_calls', 'message': {'content': None, 'reasoning_content': 'private', 'tool_calls': calls}}]}) as request:
            result = dialogue.tool_reply([{'role': 'user', 'content': 'What can you see?'}], [{'type': 'function'}])
        self.assertEqual(request.call_args.args[0], '/v1/chat/completions')
        self.assertEqual(request.call_args.args[1]['reasoning_effort'], 'none')
        self.assertEqual(request.call_args.args[1]['tool_choice'], 'auto')
        self.assertFalse(request.call_args.args[1]['parallel_tool_calls'])
        self.assertEqual(result['tool_calls'], calls)
        self.assertNotIn('reasoning_content', result)

    def test_incomplete_model_output_is_not_accepted_as_an_action(self):
        with patch.object(dialogue, '_request', return_value={'choices': [{'finish_reason': 'length', 'message': {}}]}):
            with self.assertRaises(RuntimeError):
                dialogue.tool_reply([], [])


if __name__ == '__main__':
    unittest.main()
