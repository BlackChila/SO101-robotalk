"""Bounded setup knowledge and the read-only Realtime HTTP boundary."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_web
import project_info


class ProjectInfoTests(unittest.TestCase):
    def test_every_mode_fits_the_context_budget_and_has_only_its_speech_provider(self):
        for mode in ("realtime", "piper", "qwen"):
            with self.subTest(mode=mode):
                result = project_info.get_project_info(mode, dialogue_model="qwen/qwen3.8-27b",
                                                       realtime_model="configured-realtime-model")
                encoded = json.dumps(result, ensure_ascii=False)
                self.assertLessEqual(len(encoded.split()), project_info.MAX_PROJECT_INFO_WORDS)
                self.assertLessEqual(len(encoded.encode()), project_info.MAX_PROJECT_INFO_BYTES)
                active = result["activeConversation"]
                if mode == "realtime":
                    self.assertEqual(active["dialogue"]["model"], "configured-realtime-model")
                    self.assertIsNone(active["dialogue"]["parametersBillions"])
                else:
                    self.assertEqual(active["dialogue"]["parametersBillions"], 27)
                    self.assertEqual(active["speechRecognition"]["parametersBillions"], 1.7)
                    if mode == "piper":
                        self.assertEqual(active["speechOutput"]["engine"], "Piper")
                        self.assertIsNone(active["speechOutput"]["parametersBillions"])
                    else:
                        self.assertEqual(active["speechOutput"]["model"], "Qwen3-TTS-12Hz-1.7B-CustomVoice")
                self.assertIn("https://huggingface.co/allenai/MolmoAct2-SO100_101", result["background"])
                self.assertIn("The Robot Studio", result["background"])

    def test_unknown_configured_dialogue_model_never_inherits_reference_parameter_count(self):
        result = project_info.get_project_info("piper", dialogue_model="custom/example-42b", voice="Amy")
        self.assertEqual(result["activeConversation"]["dialogue"]["model"], "custom/example-42b")
        self.assertIsNone(result["activeConversation"]["dialogue"]["parametersBillions"])
        self.assertEqual(result["activeConversation"]["voice"], "Amy")

    def test_oversized_reference_fails_instead_of_flooding_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.md"
            for content in ("word " * 901, "ä" * project_info.MAX_PROJECT_INFO_BYTES):
                path.write_text(content)
                with patch.object(project_info, "REFERENCE_PATH", path):
                    with self.assertRaises(RuntimeError):
                        project_info.get_project_info("realtime")

    def test_prompt_only_includes_narrow_routing_guidance_not_the_reference(self):
        guide = project_info.PROJECT_INFO_INSTRUCTIONS
        self.assertIn("ausdrücklichen Fragen", guide)
        self.assertIn("Nachfragen", guide)
        self.assertIn("Nicht bei Begrüßungen", guide)
        self.assertIn("ein bis drei", guide)
        self.assertNotIn("27 Milliarden", guide)
        self.assertNotIn("# SO101", guide)

    def test_realtime_endpoint_is_guarded_and_independent_of_hardware_and_model_loading(self):
        async def request(headers, **kwargs):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=asr_web.app),
                                         base_url="http://testserver") as client:
                return await client.post("/api/conversation/realtime/project-info", headers=headers, **kwargs)

        with patch.object(asr_web, "camera_session") as camera, \
             patch.object(asr_web, "policy_session") as policy, \
             patch.object(asr_web, "conversation_motion_status") as motion, \
             patch.object(asr_web, "start_conversation_task") as task, \
             patch.object(asr_web, "reset_conversation_robot") as reset, \
             patch.object(asr_web.conversation_llm, "model_status") as dialogue_status, \
             patch.object(asr_web.realtime_voice, "REALTIME_MODEL", "test-realtime"):
            denied = asyncio.run(request({}))
            self.assertEqual(denied.status_code, 403)
            response = asyncio.run(request({"x-so101-conversation": "realtime-tool"}, json={"mode": "piper"}))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.json()["activeConversation"]["dialogue"]["model"], "test-realtime")
            self.assertEqual(response.json()["activeConversation"]["mode"], "ChatGPT Realtime")
            for component in (camera, policy, motion, task, reset, dialogue_status):
                self.assertEqual(component.mock_calls, [])

    def test_missing_reference_is_a_read_only_unavailability_response(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(project_info, "REFERENCE_PATH", Path(directory) / "missing.md"):
            with self.assertRaises(asr_web.HTTPException) as error:
                asr_web.conversation_realtime_project_info(
                    type("Request", (), {"headers": {"x-so101-conversation": "realtime-tool"}})())
            self.assertEqual(error.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
