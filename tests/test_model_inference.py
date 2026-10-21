"""Validate the one-active-model registry without loading checkpoints."""

import os
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_inference  # noqa: E402


class ModelInferenceTests(unittest.TestCase):
    def test_live_chunk_rejects_nonfinite_action_before_executor(self) -> None:
        action = dict.fromkeys(model_inference.JOINTS, 0.0)
        action["elbow_flex"] = math.nan
        report = {"model": "molmoact2", "hardwareCommands": False,
                  "actionCount": 1, "actions": [action]}
        with (patch.object(model_inference.session, "predict_chunk", return_value=report),
              patch.object(model_inference.session, "stop") as stop):
            with self.assertRaisesRegex(RuntimeError, "Ungültiger Aktionsblock"):
                model_inference.predict_physical_chunk("molmoact2", "Ball",
                                                       observation_npz="/tmp/camera.npz", state={})
        stop.assert_called_once()

    def test_model_registry_only_advertises_conversation_policy(self) -> None:
        registry = model_inference.models()
        self.assertEqual([model["id"] for model in registry], ["molmoact2"])
        self.assertEqual(registry[0]["cameraProfile"]["geometry"], "overhead_x5_4x3")

    def test_removed_policies_are_rejected_before_worker_access(self) -> None:
        with patch.object(model_inference.session, "set_task") as task:
            for model in ("flux3", "g05"):
                with self.subTest(model=model), self.assertRaises(ValueError):
                    model_inference.infer(model, "move")
        task.assert_not_called()

    def test_each_model_uses_the_same_single_session(self) -> None:
        for model_id, blocker_name in (("molmoact2", "molmo_blocker"),):
            with self.subTest(model=model_id):
                report = {"model": model_id, "hardwareCommands": False, "actionCount": 1,
                          "firstAction": dict.fromkeys(model_inference.JOINTS, 0.0)}
                with (
                    patch.object(model_inference, blocker_name, return_value=None),
                    patch.object(model_inference.session, "set_task", return_value=report) as set_task,
                ):
                    self.assertEqual(model_inference.infer(model_id, "Greif den Ball"), report)
                    set_task.assert_called_once_with(model_id, "Greif den Ball")

    def test_worker_cannot_claim_motor_commands(self) -> None:
        report = {"model": "molmoact2", "hardwareCommands": True, "actionCount": 1,
                  "firstAction": dict.fromkeys(model_inference.JOINTS, 0.0)}
        with (
            patch.object(model_inference, "molmo_blocker", return_value=None),
            patch.object(model_inference.session, "set_task", return_value=report),
            patch.object(model_inference.session, "stop") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "Ungültiger"):
                model_inference.infer("molmoact2", "Hallo")
            stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
