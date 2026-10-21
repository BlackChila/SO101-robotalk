"""CPU-only contract checks for the persistent MolmoAct2 shadow session."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import molmoact2_session as session  # noqa: E402


class _FakeRuntime:
    starts = 0
    tasks: list[str] = []

    def __init__(self) -> None:
        type(self).starts += 1

    def predict(self, task: str) -> dict:
        type(self).tasks.append(task)
        return {
            "model": "molmoact2",
            "prompt": task,
            "actionCount": 30,
            "firstAction": dict.fromkeys(session.JOINTS, 0.0),
            "hardwareCommands": False,
        }


class _Value:
    def clone(self):
        return self


class _Vector:
    shape = (6,)

    def squeeze(self, _dim):
        return self

    def cpu(self):
        return self

    def __iter__(self):
        return iter((0.0,) * 6)


class _Action:
    shape = (1, 30, 6)

    def __getitem__(self, _index):
        return _Vector()


class _Processor:
    def __init__(self, events: list[str]):
        self.events = events

    def reset(self):
        self.events.append("processor_reset")

    def __call__(self, observation):
        if isinstance(observation, dict):
            self.events.append("task:" + observation["task"])
            return observation
        return observation


class _Policy:
    def __init__(self, events: list[str]):
        self.events = events

    def reset(self):
        self.events.append("policy_reset")

    def predict_action_chunk(self, observation):
        self.events.append("infer:" + observation["task"])
        return _Action()


class MolmoSessionTests(unittest.TestCase):
    def test_physical_chunk_uses_measured_joints_and_processes_all_actions(self):
        class Policy:
            def reset(self):
                pass

            def predict_action_chunk(self, observation):
                self.state = observation["observation.state"].clone()
                return torch.zeros((1, 30, 6), dtype=torch.float32)

        class Processor:
            def reset(self):
                pass

            def __call__(self, value):
                return value

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "camera.npz"
            np.savez(path, cam0=np.zeros((1, 720, 960, 3), np.uint8),
                     cam1=np.zeros((1, 720, 960, 3), np.uint8))
            runtime = session.MolmoRuntime.__new__(session.MolmoRuntime)
            runtime.torch = torch
            runtime.policy = Policy()
            runtime.pre = Processor()
            runtime.post = Processor()
            runtime.base_observation = {"observation.state": torch.ones(6)}
            runtime.load_seconds = 0.0
            joints = dict.fromkeys(session.JOINTS, 2.0)
            with patch.object(torch.cuda, "synchronize"):
                result = runtime.predict("Ball", str(path), joints, all_actions=True)
        self.assertEqual(result["actionCount"], 30)
        self.assertEqual(len(result["actions"]), 30)
        self.assertTrue(torch.equal(runtime.policy.state, torch.full((6,), 2.0)))
        self.assertEqual(result["observation"], "live_overhead_x5_measured_joint_state")

    def test_warm_creates_runtime_before_first_prompt(self):
        _FakeRuntime.starts = 0
        _FakeRuntime.tasks = []
        commands = io.StringIO('{"op":"warm"}\n{"op":"set_task","task":"go"}\n')
        output = io.StringIO()
        errors = io.StringIO()
        session.serve(commands, output, errors, runtime_factory=_FakeRuntime)
        reports = [json.loads(line.removeprefix("RESULT_JSON:"))
                   for line in output.getvalue().splitlines()]
        self.assertEqual(_FakeRuntime.starts, 1)
        self.assertEqual(_FakeRuntime.tasks, ["go"])
        self.assertEqual(reports[0], {"model": "molmoact2", "ready": True,
                                      "hardwareCommands": False})
        self.assertEqual(errors.getvalue(), "")

    def test_live_camera_pair_maps_overhead_to_cam0_and_x5_to_cam1(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "camera.npz"
            np.savez(path, cam0=np.full((1, 720, 960, 3), 51, np.uint8),
                     cam1=np.full((1, 720, 960, 3), 153, np.uint8))
            images = session.load_live_camera_images(str(path), torch)
        self.assertEqual(tuple(images["observation.images.cam0"].shape), (3, 720, 960))
        self.assertAlmostEqual(images["observation.images.cam0"][0, 0, 0].item(), 51 / 255)
        self.assertAlmostEqual(images["observation.images.cam1"][0, 0, 0].item(), 153 / 255)

    def test_worker_keeps_one_runtime_for_repeated_tasks(self):
        _FakeRuntime.starts = 0
        _FakeRuntime.tasks = []
        commands = io.StringIO(
            '{"op":"set_task","task":" first "}\n'
            '{"op":"set_task","task":"second"}\n'
            '{"op":"stop"}\n'
            '{"op":"set_task","task":"ignored"}\n'
        )
        output = io.StringIO()
        errors = io.StringIO()
        session.serve(commands, output, errors, runtime_factory=_FakeRuntime)

        reports = [json.loads(line.removeprefix("RESULT_JSON:")) for line in output.getvalue().splitlines()]
        self.assertEqual(_FakeRuntime.starts, 1)
        self.assertEqual(_FakeRuntime.tasks, ["first", "second"])
        self.assertEqual([report["sequence"] for report in reports], [1, 2])
        self.assertTrue(all(report["hardwareCommands"] is False for report in reports))
        self.assertEqual(errors.getvalue(), "")

    def test_invalid_task_does_not_load_or_terminate_worker(self):
        _FakeRuntime.starts = 0
        _FakeRuntime.tasks = []
        commands = io.StringIO('{"op":"set_task","task":" "}\n{"op":"set_task","task":"valid"}\n')
        output = io.StringIO()
        session.serve(commands, output, io.StringIO(), runtime_factory=_FakeRuntime)
        lines = output.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("ERROR_JSON:"))
        self.assertTrue(lines[1].startswith("RESULT_JSON:"))
        self.assertEqual(_FakeRuntime.starts, 1)
        self.assertEqual(_FakeRuntime.tasks, ["valid"])

    def test_every_task_resets_policy_before_synchronous_inference(self):
        events: list[str] = []
        runtime = session.MolmoRuntime.__new__(session.MolmoRuntime)
        runtime.torch = SimpleNamespace(
            inference_mode=contextlib.nullcontext,
            cuda=SimpleNamespace(synchronize=lambda: None),
            isfinite=lambda _values: SimpleNamespace(all=lambda: True),
        )
        runtime.policy = _Policy(events)
        runtime.pre = _Processor(events)
        runtime.post = _Processor(events)
        runtime.base_observation = {"observation.state": _Value()}
        runtime.load_seconds = 1.0

        first = runtime.predict("first")
        second = runtime.predict("second")

        self.assertEqual(
            events,
            ["policy_reset", "processor_reset", "processor_reset", "task:first", "infer:first",
             "policy_reset", "processor_reset", "processor_reset", "task:second", "infer:second"],
        )
        self.assertTrue(first["staleActionsInvalidated"])
        self.assertTrue(second["staleActionsInvalidated"])
        self.assertEqual(second["inferenceMode"], "synchronous_shadow")
        self.assertFalse(second["hardwareCommands"])


if __name__ == "__main__":
    unittest.main()
