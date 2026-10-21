"""Credential exchange contract for the browser Realtime conversation mode."""

import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import httpx
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_web  # noqa: E402
import realtime_voice  # noqa: E402


class RealtimeVoiceTests(unittest.TestCase):
    def test_http_tool_starts_worker_directly_and_hands_back_motor_owner(self) -> None:
        """Exercise the real API and task thread with simulated cameras and motors."""
        session_id = "a" * 32
        pose = dict.fromkeys(("shoulder_pan", "shoulder_lift", "elbow_flex",
                              "wrist_flex", "wrist_roll", "gripper"), 0.0)
        commands = []
        lock = threading.Lock()

        def owner(_session, command):
            commands.append(command["op"])
            if command["op"] == "snapshot":
                Path(command["observation_path"]).touch()
                return {"status": "observed", "model": "molmoact2",
                        "observation_path": command["observation_path"], "state": pose}
            if command["op"] == "execute":
                asr_web._active_task["stop"].set()
                return {"status": "executed", "executedActions": 1}
            return {"status": command["op"], "speechGripperAvailable": True}

        async def exercise():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=asr_web.app),
                                         base_url="http://testserver") as client:
                result = await client.post('/api/conversation/task/start',
                    headers={"x-so101-conversation": "realtime-tool"}, json={
                        "sessionId": session_id, "instruction": "Lege den Ball in den Topf", "callId": "call-1"})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["taskRun"]["model"], "molmoact2")
                for removed in ("propose", "confirm", "cancel"):
                    response = await client.post(f'/api/conversation/task/{removed}', json={})
                    self.assertEqual(response.status_code, 404)


        with tempfile.TemporaryDirectory() as directory, \
             patch.object(asr_web, "ROOT", Path(directory)), \
             patch.object(asr_web, "conversation_motion_status", return_value={
                 "sessionId": session_id, "state": "holding"}), \
             patch.object(asr_web, "_active_task", None), \
             patch.object(asr_web, "_last_task", None), \
             patch.object(asr_web, "_conversation_task_calls", {}), \
             patch.object(asr_web, "_policy_lock", lock), \
             patch.object(asr_web, "policy_session", SimpleNamespace(preload=Mock())), \
             patch.object(asr_web, "camera_session", SimpleNamespace(select=Mock())), \
             patch.object(asr_web, "conversation_holder_command", side_effect=owner), \
             patch.object(asr_web, "predict_physical_chunk", return_value={"actions": [pose]}):
            (Path(directory) / "outputs").mkdir()
            asyncio.run(exercise())
            self.assertTrue(lock.acquire(timeout=3), "Task worker did not finish")
            lock.release()
            self.assertEqual(commands, ["task_active", "snapshot", "execute", "task_inactive"])
            self.assertEqual(asr_web._last_task["actions"], 1)

    def test_post_task_return_remains_available_after_verified_hold(self) -> None:
        session_id = "a" * 32
        with tempfile.TemporaryDirectory() as directory, patch.object(asr_web, "ROOT", Path(directory)):
            outputs = Path(directory) / "outputs"
            outputs.mkdir()
            (outputs / f"conversation-motion-{session_id}.json").write_text(json.dumps({
                "state": "stopped", "follower_torque_holding": True,
                "task_was_started": True, "ended_at_unix": asr_web.time.time(),
            }))
            self.assertIsNotNone(asr_web.recoverable_conversation_report(session_id))
        with patch.object(asr_web, "conversation_motion_status", return_value={
                "state": "holding", "taskWasStarted": True}), \
             patch.object(asr_web, "_active_task", None), \
             patch.object(asr_web.face_tracking_session, "disable"), \
             patch.object(asr_web, "send_conversation_motion") as send:
            result = asr_web.conversation_motion_return(
                asr_web.ConversationMotionSession(sessionId=session_id))
            self.assertEqual(result["status"], "returning")
            send.assert_called_once_with(session_id, {"op": "return_to_start"}, mark_return=True)

    def test_confirmed_task_uses_conversation_motor_owner_and_restores_gripper(self) -> None:
        pose = dict.fromkeys(("shoulder_pan", "shoulder_lift", "elbow_flex",
                              "wrist_flex", "wrist_roll", "gripper"), 0.0)
        commands = []
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            output.mkdir()
            run = {"id": "test", "model": "molmoact2", "prompt": "Put the ball on the tray",
                   "state": "loading", "chunks": 0, "actions": 0, "startedAt": 1.0,
                   "endedAt": None, "message": "loading", "generation": 0,
                   "inferenceGeneration": -1, "executedGeneration": -1,
                   "stop": threading.Event(), "conversationSessionId": "a" * 32,
                   "epochPath": output / "ui-robot-epoch-test.txt"}
            run["epochPath"].write_text("0")

            def owner(_session, command):
                commands.append(command["op"])
                if command["op"] == "snapshot":
                    Path(command["observation_path"]).touch()
                    return {"status": "observed", "model": "molmoact2",
                            "observation_path": command["observation_path"], "state": pose}
                if command["op"] == "execute":
                    run["stop"].set()
                    return {"status": "executed", "executedActions": 1}
                if command["op"] == "task_inactive":
                    return {"status": "task_inactive", "speechGripperAvailable": True}
                return {"status": "task_active"}

            lock = threading.Lock()
            lock.acquire()
            with patch.object(asr_web, "ROOT", Path(directory)), \
                 patch.object(asr_web, "_active_task", run), \
                 patch.object(asr_web, "_policy_lock", lock), \
                 patch.object(asr_web, "conversation_holder_command", side_effect=owner), \
                 patch.object(asr_web, "holder_command") as other_owner, \
                 patch.object(asr_web, "camera_session", SimpleNamespace(
                     select=Mock(side_effect=lambda _: commands.append("camera")))), \
                 patch.object(asr_web, "policy_session", SimpleNamespace(
                     preload=Mock(side_effect=lambda _: commands.append("preload")))), \
                 patch.object(asr_web, "predict_physical_chunk", return_value={"actions": [pose]}):
                asr_web.physical_task_loop(run)
            self.assertEqual(commands, ["preload", "camera", "task_active", "snapshot",
                                        "execute", "task_inactive"])
            self.assertEqual(run["state"], "stopped")
            self.assertTrue(run["speechGripperAvailable"])
            other_owner.assert_not_called()

    def test_stop_during_task_loading_keeps_talking_gripper_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            output.mkdir()
            stop = threading.Event()
            run = {"id": "loading-test", "model": "molmoact2", "prompt": "Move the ball",
                   "state": "loading", "chunks": 0, "actions": 0, "startedAt": 1.0,
                   "endedAt": None, "message": "loading", "generation": 0,
                   "inferenceGeneration": -1, "executedGeneration": -1,
                   "stop": stop, "conversationSessionId": "a" * 32,
                   "epochPath": output / "ui-robot-epoch-loading-test.txt"}
            run["epochPath"].write_text("0")
            lock = threading.Lock()
            lock.acquire()

            def finish_preload(_model):
                stop.set()
                return {"ready": True, "hardwareCommands": False}

            with patch.object(asr_web, "ROOT", Path(directory)), \
                 patch.object(asr_web, "_active_task", run), \
                 patch.object(asr_web, "_policy_lock", lock), \
                 patch.object(asr_web, "policy_session", SimpleNamespace(preload=finish_preload)), \
                 patch.object(asr_web, "camera_session", SimpleNamespace(select=Mock())) as camera, \
                 patch.object(asr_web, "conversation_holder_command") as motor:
                asr_web.physical_task_loop(run)
            self.assertEqual(run["state"], "stopped")
            camera.select.assert_not_called()
            motor.assert_not_called()

    def test_direct_tasks_update_active_run_and_restart_after_stop(self):
        session = "a" * 32
        tool = SimpleNamespace(headers={"x-so101-conversation": "realtime-tool"})
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(asr_web, "ROOT", Path(directory)), \
             patch.object(asr_web, "conversation_motion_status", return_value={
                 "sessionId": session, "state": "holding"}) as motion, \
             patch.object(asr_web, "_active_task", None), \
             patch.object(asr_web, "_conversation_task_calls", {}), \
             patch.object(asr_web, "_policy_lock", threading.Lock()), \
             patch.object(asr_web.threading, "Thread") as worker:
            (Path(directory) / "outputs").mkdir()
            def request(text, call):
                return asr_web.ConversationTaskRequest(sessionId=session, instruction=text, callId=call)
            first = request("Lege den Ball in den Topf", "call-1")
            with self.assertRaises(HTTPException) as denied:
                asr_web.conversation_task_start(first, SimpleNamespace(headers={}))
            self.assertEqual(denied.exception.status_code, 403)
            started = asr_web.conversation_task_start(first, tool)
            self.assertEqual(started["status"], "loading")
            run = asr_web._active_task
            motion.return_value["state"] = "task"
            run["state"] = "running"
            second = request("Lege den Ball auf das Tablett", "call-2")
            result = asr_web.conversation_task_start(second, tool)
            self.assertEqual(result["status"], "updated")
            self.assertIs(asr_web._active_task, run)
            self.assertEqual(run["prompt"], second.instruction)
            self.assertEqual(run["generation"], 1)
            self.assertEqual(run["epochPath"].read_text(), "1")
            worker.return_value.start.assert_called_once()
            # Duplicate delivery must neither restart nor overwrite with an older command.
            asr_web.conversation_task_start(first, tool)
            asr_web.conversation_task_start(second, tool)
            self.assertEqual(run["generation"], 1)
            self.assertEqual(run["prompt"], second.instruction)
            third = request("Greife den Ball", "call-3")
            run["stop"].set()
            with self.assertRaises(HTTPException):
                asr_web.conversation_task_start(third, tool)
            run["stop"].clear()
            run["conversationSessionId"] = "b" * 32
            with self.assertRaises(HTTPException):
                asr_web.conversation_task_start(third, tool)
            # After the worker hands control back, the next task starts normally.
            asr_web._active_task = None
            asr_web._policy_lock.release()
            motion.return_value["state"] = "holding"
            self.assertEqual(asr_web.conversation_task_start(third, tool)["status"], "loading")
            self.assertEqual(worker.return_value.start.call_count, 2)
            asr_web._policy_lock.release()

    def test_direct_task_rejects_invalid_session_and_multisentence_instruction(self):
        tool = SimpleNamespace(headers={"x-so101-conversation": "realtime-tool"})
        with patch.object(asr_web, "conversation_motion_status", return_value={
                 "sessionId": "b" * 32, "state": "holding"}), \
             patch.object(asr_web.threading, "Thread") as worker:
            for instruction, code in (("Greife den Ball", 409), ("Greife den Ball. Dann winke.", 422), ("   ", 422)):
                with self.assertRaises(HTTPException) as denied:
                    asr_web.conversation_task_start(asr_web.ConversationTaskRequest(
                        sessionId="a" * 32, instruction=instruction, callId="call"), tool)
                self.assertEqual(denied.exception.status_code, code)
            worker.assert_not_called()

    def test_root_env_file_is_used_when_process_key_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("OPENAI_API_KEY='test-file-key'\n")
            with patch.dict(os.environ, {}, clear=True), patch.object(realtime_voice, "ENV_FILE", env_file):
                self.assertTrue(realtime_voice.configured())
                self.assertEqual(realtime_voice._api_key(), "test-file-key")
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test-process-key"}):
                    self.assertEqual(realtime_voice._api_key(), "test-process-key")

    def test_token_endpoint_requires_operator_call_and_holding_motion(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-server-key"}):
            with self.assertRaises(HTTPException) as missing_call:
                asyncio.run(asr_web.conversation_realtime_token(SimpleNamespace(headers={})))
            self.assertEqual(missing_call.exception.status_code, 403)
            with patch.object(asr_web, "conversation_motion_status", return_value={"state": "intro"}):
                with self.assertRaises(HTTPException) as early:
                    asyncio.run(asr_web.conversation_realtime_token(SimpleNamespace(
                        headers={"x-so101-conversation": "operator-call"})))
            self.assertEqual(early.exception.status_code, 409)

    def test_realtime_intro_can_connect_early_but_only_live_intro_receives_levels(self):
        session = 'a' * 32
        with patch.object(realtime_voice, 'configured', return_value=True), \
             patch.object(asr_web, '_realtime_motion_sessions', set()), \
             patch.object(asr_web, 'run_in_threadpool', new_callable=AsyncMock, return_value='ek_test'), \
             patch.object(asr_web, 'send_conversation_motion') as send:
            for state in ('starting', 'positioning', 'intro'):
                motion = {'state': state, 'sessionId': session, 'active': True, 'realtimeIntro': True}
                with patch.object(asr_web, 'conversation_motion_status', return_value=motion):
                    result = asyncio.run(asr_web.conversation_realtime_token(
                        SimpleNamespace(headers={'x-so101-conversation': 'operator-call'})))
                    self.assertEqual(json.loads(result.body)['value'], 'ek_test')
                    level = asr_web.conversation_motion_level(asr_web.ConversationMotionLevel(sessionId=session, level=.5))
                    self.assertEqual(level['status'], 'ok' if state == 'intro' else 'ignored')
            self.assertIn(session, asr_web._realtime_motion_sessions)
            send.assert_called_once()

    def test_speech_levels_are_ignored_while_reset_positions_the_arm(self):
        for state in ('starting', 'positioning'):
            with self.subTest(state=state), \
                 patch.object(asr_web, 'conversation_motion_status', return_value={
                     'state': state, 'realtimeIntro': False}), \
                 patch.object(asr_web, 'send_conversation_motion') as send:
                result = asr_web.conversation_motion_level(
                    asr_web.ConversationMotionLevel(sessionId='a' * 32, level=.5))
                self.assertEqual(result['status'], 'ignored')
                send.assert_not_called()

    def test_realtime_preload_warms_policy_without_camera_or_motor_commands(self) -> None:
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

        session_id = "a" * 32
        selection = asr_web.RealtimePreloadRequest(sessionId=session_id)
        request = SimpleNamespace(headers={"x-so101-conversation": "operator-call"})
        policy = SimpleNamespace(model_id=None, preload=Mock(return_value={
            "model": "molmoact2", "ready": True, "hardwareCommands": False}))
        camera = SimpleNamespace(select=Mock())
        with patch.object(asr_web, "conversation_motion_status", return_value={
                "sessionId": session_id, "state": "holding"}), \
             patch.object(asr_web, "available_models", return_value=[{
                 "id": "molmoact2", "available": True}]), \
             patch.object(asr_web, "policy_session", policy), \
             patch.object(asr_web, "camera_session", camera), \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
             patch.object(asr_web, "conversation_holder_command") as motor:
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(asr_web.conversation_realtime_molmo_preload(
                    SimpleNamespace(headers={}), selection))
            self.assertEqual(denied.exception.status_code, 403)
            self.assertEqual(asyncio.run(asr_web.conversation_realtime_molmo_preload(
                request, selection)), {"model": "molmoact2", "ready": True,
                                      "hardwareCommands": False})
            policy.preload.assert_called_once_with("molmoact2")
            camera.select.assert_not_called()
            motor.assert_not_called()

    def test_realtime_preload_can_run_before_intro_and_rejects_an_occupied_arm(self) -> None:
        async def inline(function, *args):
            return function(*args)

        policy = SimpleNamespace(model_id=None, preload=Mock(return_value={
            "model": "molmoact2", "ready": True, "hardwareCommands": False}))
        request = SimpleNamespace(headers={"x-so101-conversation": "operator-call"})
        with patch.object(asr_web, "conversation_motion_status", return_value={
                "sessionId": None, "state": "idle", "occupied": False}) as motion, \
             patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "torque_state", return_value=("idle", None)), \
             patch.object(asr_web, "available_models", return_value=[{"id": "molmoact2", "available": True}]), \
             patch.object(asr_web, "policy_session", policy), \
             patch.object(asr_web, "run_in_threadpool", side_effect=inline), \
             patch.object(asr_web, "conversation_holder_command") as motor:
            result = asyncio.run(asr_web.conversation_realtime_molmo_preload(
                request, asr_web.RealtimePreloadRequest()))
            self.assertTrue(result["ready"])
            motion.return_value["occupied"] = True
            with self.assertRaises(HTTPException) as busy:
                asyncio.run(asr_web.conversation_realtime_molmo_preload(
                    request, asr_web.RealtimePreloadRequest()))
            self.assertEqual(busy.exception.status_code, 409)
            policy.preload.assert_called_once_with("molmoact2")
            motor.assert_not_called()

    def test_status_does_not_wait_for_model_warmup_locks(self) -> None:
        class BusyWorker:
            @property
            def ready_model_id(self):
                raise AssertionError("Status tried to take the busy model lock")
            @property
            def model_id(self):
                raise AssertionError("Status tried to take the busy camera lock")

        lock = threading.Lock()
        lock.acquire()
        with patch.object(asr_web, "_policy_lock", lock), \
             patch.object(asr_web, "policy_session", BusyWorker()), \
             patch.object(asr_web, "camera_session", BusyWorker()), \
             patch.object(asr_web, "reset_state", return_value=("idle", None)), \
             patch.object(asr_web, "torque_state", return_value=("idle", None)), \
             patch.object(asr_web, "reset_blocker", return_value=None), \
             patch.object(asr_web, "static_reset_blocker", return_value=None), \
             patch.object(asr_web, "conversation_motion_status", return_value={"occupied": False, "active": False}), \
             patch.object(asr_web, "task_status", return_value=None):
            result = asr_web.status()
            self.assertIsNone(result["modelSession"])
            self.assertIsNone(result["cameraModel"])
        lock.release()

    def test_server_mints_only_ephemeral_key_with_realtime_session(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): self.close()

        def fake_urlopen(request, timeout):
            self.assertEqual(timeout, 15)
            self.assertEqual(request.full_url, realtime_voice.CLIENT_SECRETS_URL)
            self.assertEqual(request.get_header("Authorization"), "Bearer test-server-key")
            session = json.loads(request.data)["session"]
            self.assertEqual(session["type"], "realtime")
            self.assertEqual(session["model"], realtime_voice.REALTIME_MODEL)
            self.assertEqual(session["audio"]["output"]["voice"], "marin")
            self.assertEqual(session["audio"]["input"]["transcription"]["model"], "gpt-4o-mini-transcribe")
            self.assertEqual(session["tools"][0]["name"], "execute_molmo_task")
            self.assertEqual(session["tools"][1]["name"], "reset_robot")
            self.assertEqual(session["tools"][1]["parameters"]["properties"], {})
            self.assertEqual(session["tools"][2]["name"], "look_at_scene")
            self.assertEqual(session["tools"][3]["name"], "search_web")
            info_tool = session["tools"][4]
            self.assertEqual(info_tool["name"], "get_project_info")
            self.assertEqual(info_tool["parameters"], {
                "type": "object", "properties": {}, "required": [], "additionalProperties": False})
            self.assertEqual(info_tool["description"], realtime_voice.PROJECT_INFO_TOOL_DESCRIPTION)
            self.assertIn(realtime_voice.PROJECT_INFO_INSTRUCTIONS, session["instructions"])
            creator_tool = session["tools"][5]
            self.assertEqual(creator_tool["name"], "get_creator_info")
            self.assertEqual(creator_tool["parameters"], {
                "type": "object", "properties": {}, "required": [], "additionalProperties": False})
            self.assertEqual(creator_tool["description"], realtime_voice.CREATOR_INFO_TOOL_DESCRIPTION)
            self.assertIn(realtime_voice.CREATOR_INFO_INSTRUCTIONS, session["instructions"])
            self.assertIn("ohne zu sagen, welches Detail", session["instructions"])
            self.assertIn("Prüfe bei look_at_scene beide verfügbaren Perspektiven", session["instructions"])
            self.assertIn("bereits aufrecht gedreht", session["instructions"])
            self.assertNotIn("Wrist camera kann seitlich", session["instructions"])
            self.assertIn("erwähne ihn nicht", session["instructions"])
            self.assertIn("without naming cameras", session["tools"][2]["description"])
            self.assertIn("ohne feste Schlüsselwörter", session["instructions"])
            self.assertEqual(session["audio"]["input"]["turn_detection"], {
                "type": "semantic_vad", "create_response": False, "interrupt_response": False})
            self.assertIn("JEDEN Folgeauftrag", session["instructions"])
            self.assertIn("Sprich als der Roboter in der Ich-Form", session["instructions"])
            self.assertIn("Bewegung deines Arms", session["instructions"])
            self.assertIn("höchstens ein Satz", session["instructions"])
            self.assertIn("Frage nicht nach Zustimmung oder Bestätigung", session["instructions"])
            self.assertIn("Rufe DANACH sofort execute_molmo_task auf", session["instructions"])
            self.assertNotIn("test-server-key", request.data.decode())
            return Response(b'{"value":"ek_short_lived"}')

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-server-key"}), \
             patch.object(realtime_voice, "urlopen", side_effect=fake_urlopen):
            self.assertEqual(realtime_voice.create_client_secret(), "ek_short_lived")
            with patch.object(asr_web, "conversation_motion_status", return_value={"state": "holding"}), \
                 patch.object(asr_web, "run_in_threadpool", new_callable=AsyncMock,
                              return_value="ek_short_lived"):
                result = asyncio.run(asr_web.conversation_realtime_token(SimpleNamespace(
                    headers={"x-so101-conversation": "operator-call"})))
            self.assertEqual(json.loads(result.body),
                             {"value": "ek_short_lived", "model": realtime_voice.REALTIME_MODEL})
            self.assertEqual(result.headers["Cache-Control"], "no-store")
            self.assertNotIn("test-server-key", str(result.body))

    def test_selected_realtime_voice_is_sent_with_new_session(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): self.close()

        def fake_urlopen(request, timeout):
            self.assertEqual(json.loads(request.data)["session"]["audio"]["output"]["voice"], "cedar")
            return Response(b'{"value":"ek_short_lived"}')

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-server-key"}), \
             patch.object(realtime_voice, "urlopen", side_effect=fake_urlopen):
            self.assertEqual(realtime_voice.create_client_secret("cedar"), "ek_short_lived")
            with self.assertRaises(ValueError):
                realtime_voice.create_client_secret("unknown")
            with patch.object(asr_web, "conversation_motion_status", return_value={"state": "holding"}), \
                 patch.object(asr_web, "run_in_threadpool", new_callable=AsyncMock,
                              return_value="ek_short_lived") as mint:
                result = asyncio.run(asr_web.conversation_realtime_token(
                    SimpleNamespace(headers={"x-so101-conversation": "operator-call"}),
                    asr_web.RealtimeVoiceRequest(voice="cedar")))
                self.assertEqual(json.loads(result.body)["value"], "ek_short_lived")
                mint.assert_awaited_once_with(realtime_voice.create_client_secret, "cedar", False, "German")

    def test_voice_only_token_does_not_require_follower_hold(self) -> None:
        selection = asr_web.RealtimeVoiceRequest(voice="marin", voiceOnly=True)
        call = SimpleNamespace(headers={"x-so101-conversation": "operator-call"})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-server-key"}), \
             patch.object(asr_web, "conversation_motion_status",
                          return_value={"state": "idle", "active": False}), \
             patch.object(asr_web, "run_in_threadpool", new_callable=AsyncMock,
                          return_value="ek_short_lived") as mint:
            result = asyncio.run(asr_web.conversation_realtime_token(call, selection))
            self.assertEqual(json.loads(result.body)["value"], "ek_short_lived")
            mint.assert_awaited_once_with(realtime_voice.create_client_secret, "marin", True, "German")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-server-key"}), \
             patch.object(asr_web, "conversation_motion_status",
                          return_value={"state": "intro", "active": True}):
            with self.assertRaises(HTTPException) as active:
                asyncio.run(asr_web.conversation_realtime_token(call, selection))
            self.assertEqual(active.exception.status_code, 409)

    def test_voice_only_session_has_no_motor_tool(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): self.close()

        def fake_urlopen(request, timeout):
            session = json.loads(request.data)["session"]
            self.assertEqual(session["audio"]["input"]["turn_detection"], {
                "type": "semantic_vad", "create_response": False, "interrupt_response": False})
            self.assertEqual([tool["name"] for tool in session["tools"]], ["look_at_scene", "search_web", "get_project_info", "get_creator_info"])
            self.assertEqual(session["tools"][-1]["parameters"]["properties"], {})
            self.assertEqual(session["tool_choice"], "auto")
            self.assertIn("Sprich als der Roboter in der Ich-Form", session["instructions"])
            self.assertIn("nur sprechen", session["instructions"])
            return Response(b'{"value":"ek_short_lived"}')

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-server-key"}), \
             patch.object(realtime_voice, "urlopen", side_effect=fake_urlopen):
            self.assertEqual(realtime_voice.create_client_secret("marin", True), "ek_short_lived")

    def test_scene_endpoint_returns_images_without_motor_access_or_caching(self):
        payload = {"images": [{"camera": "wrist", "imageUrl": "data:image/jpeg;base64,AA=="}],
                   "unavailable": [{"camera": "overhead"}], "status": "partial"}
        with patch.object(asr_web, "run_in_threadpool", new_callable=AsyncMock, return_value=payload) as capture, \
             patch.object(asr_web, "conversation_motion_status") as motion:
            result = asyncio.run(asr_web.conversation_realtime_scene(
                SimpleNamespace(headers={"x-so101-conversation": "realtime-tool"})))
            capture.assert_awaited_once_with(asr_web.camera_session.scene_snapshot)
            motion.assert_not_called()
            self.assertEqual(json.loads(result.body), payload)
            self.assertEqual(result.headers["cache-control"], "no-store")

    def test_scene_endpoint_rejects_missing_header_and_reports_inactive_cameras(self):
        with patch.object(asr_web, "run_in_threadpool", new_callable=AsyncMock,
                          side_effect=RuntimeError("Kameras nicht aktiv")) as capture:
            with self.assertRaises(HTTPException) as rejected:
                asyncio.run(asr_web.conversation_realtime_scene(SimpleNamespace(headers={})))
            self.assertEqual(rejected.exception.status_code, 403)
            capture.assert_not_awaited()
            with self.assertRaises(HTTPException) as unavailable:
                asyncio.run(asr_web.conversation_realtime_scene(
                    SimpleNamespace(headers={"x-so101-conversation": "realtime-tool"})))
            self.assertEqual(unavailable.exception.status_code, 503)

    def test_missing_server_key_does_not_contact_openai(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            absent_file = Path(directory) / ".env"
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(realtime_voice, "ENV_FILE", absent_file), \
                 patch.object(realtime_voice, "urlopen") as outgoing:
                with self.assertRaises(HTTPException) as missing:
                    asyncio.run(asr_web.conversation_realtime_token(SimpleNamespace(
                        headers={"x-so101-conversation": "operator-call"})))
                self.assertEqual(missing.exception.status_code, 503)
                outgoing.assert_not_called()


if __name__ == "__main__":
    unittest.main()
