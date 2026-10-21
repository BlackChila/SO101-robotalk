"""Creator lookup stays compact and never acquires a model or robot."""

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
import creator_info


class CreatorInfoTests(unittest.TestCase):
    def test_curated_identity_and_hardware_distinction_fit_the_budget(self):
        result = creator_info.get_creator_info()
        text = result["background"]
        self.assertIn("Eleni Kofekidou", text)
        self.assertIn("BlackChila", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("@gmx", text)
        self.assertNotIn("2014", text)
        self.assertIn("The Robot Studio", text)
        self.assertIn("Profile.pdf", text)
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertLessEqual(len(encoded.split()), creator_info.MAX_CREATOR_INFO_WORDS)
        self.assertLessEqual(len(encoded.encode()), creator_info.MAX_CREATOR_INFO_BYTES)

    def test_full_note_is_not_in_the_initial_routing_prompt(self):
        prompt = creator_info.CREATOR_INFO_INSTRUCTIONS
        self.assertIn("get_creator_info", prompt)
        self.assertIn("get_project_info", prompt)
        self.assertIn("Do not use for greetings", creator_info.CREATOR_INFO_TOOL_DESCRIPTION)
        self.assertIn("Kein Aufruf", prompt)
        self.assertNotIn("https://www.linkedin.com", prompt)
        self.assertNotIn("Virtual Reality", prompt)

    def test_oversized_or_missing_reference_does_not_flood_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "creator.md"
            with patch.object(creator_info, "REFERENCE_PATH", path):
                with self.assertRaises(OSError):
                    creator_info.get_creator_info()
                path.write_text("word " * 351)
                with self.assertRaises(RuntimeError):
                    creator_info.get_creator_info()

    def test_endpoint_requires_tool_header_and_works_without_hardware_or_profile_fetch(self):
        async def request(headers):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=asr_web.app),
                                         base_url="http://testserver") as client:
                return await client.post("/api/conversation/realtime/creator-info", headers=headers)

        with patch.object(asr_web, "camera_session") as camera, \
             patch.object(asr_web, "policy_session") as policy, \
             patch.object(asr_web, "conversation_motion_status") as motion, \
             patch.object(asr_web, "start_conversation_task") as task, \
             patch.object(asr_web, "reset_conversation_robot") as reset, \
             patch.object(asr_web.conversation_llm, "model_status") as dialogue:
            self.assertEqual(asyncio.run(request({})).status_code, 403)
            response = asyncio.run(request({"x-so101-conversation": "realtime-tool"}))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn("Eleni Kofekidou", response.json()["background"])
            for component in (camera, policy, motion, task, reset, dialogue):
                self.assertEqual(component.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
