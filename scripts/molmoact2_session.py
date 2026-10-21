#!/usr/bin/env python3
"""Persistent, hardware-free MolmoAct2 prompt session on the official sample.

Input is one JSON command per line. ``{"op":"set_task","task":"..."}``
produces one ``RESULT_JSON:`` line; ``{"op":"stop"}`` closes the session.
No robot, camera, or motor device is opened by this module.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, TextIO

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "models" / "molmoact2" / "runtime"
SOURCE = ROOT / "models" / "molmoact2" / "source"
JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
CHECKPOINT = "lerobot/MolmoAct2-SO100_101-LeRobot"


def _valid_task(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
        raise ValueError("The task must contain 1 to 500 characters.")
    return value.strip()


def load_live_camera_images(camera_npz: str, torch) -> dict[str, Any]:
    import numpy as np

    images = {}
    with np.load(camera_npz, allow_pickle=False) as saved:
        if set(saved.files) != {"cam0", "cam1"}:
            raise ValueError("MolmoAct2 requires cam0 and cam1.")
        for role in ("cam0", "cam1"):
            rgb = saved[role]
            if rgb.shape != (1, 720, 960, 3) or rgb.dtype != np.uint8:
                raise ValueError(f"Invalid live image for {role}: {rgb.shape}")
            images[f"observation.images.{role}"] = (
                torch.from_numpy(rgb[0].copy()).permute(2, 0, 1).float() / 255
            )
    return images


class MolmoRuntime:
    """Load checkpoint once, then synchronously infer after clearing old state."""

    def __init__(self) -> None:
        import numpy as np
        import torch
        from PIL import Image
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import make_pre_post_processors
        from lerobot.policies.molmoact2.modeling_molmoact2 import MolmoAct2Policy

        from camera_profiles import crop_4x3

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable for MolmoAct2.")
        config = PreTrainedConfig.from_pretrained(RUNTIME)
        config.checkpoint_path = str(SOURCE)
        config.device = "cuda"
        config.push_to_hub = False
        # Differently tokenized tasks should not trigger CUDA graph recapture.
        config.enable_inference_cuda_graph = False
        if config.image_keys != ["observation.images.cam0", "observation.images.cam1"]:
            raise RuntimeError(f"Unexpected camera inputs: {config.image_keys}")
        if config.chunk_size != 30:
            raise RuntimeError(f"Unexpected action length: {config.chunk_size}")

        torch.manual_seed(0)
        started = time.monotonic()
        self.policy = MolmoAct2Policy.from_pretrained(RUNTIME, config=config).eval()
        self.pre, self.post = make_pre_post_processors(
            config,
            pretrained_path=str(RUNTIME),
            preprocessor_overrides={
                "molmoact2_pack_inputs": {"checkpoint_path": str(SOURCE)},
                "device_processor": {"device": "cuda"},
            },
            postprocessor_overrides={"device_processor": {"device": "cpu"}},
        )
        self.load_seconds = round(time.monotonic() - started, 2)
        self.torch = torch

        # The official sample state is in the historical joint frame. Undo it
        # exactly once because the saved processor applies the correction.
        sample_state = torch.tensor(
            [-0.52734375, 189.140625, 181.40625, 60.64453125, -3.603515625, 1.0971786975860596]
        )
        state = (sample_state - torch.tensor(config.joint_offsets)) / torch.tensor(config.joint_signs)
        self.base_observation = {"observation.state": state}
        for key, filename in zip(
            config.image_keys,
            ("sample_realsense_top_rgb.png", "sample_realsense_side_rgb.png"),
            strict=True,
        ):
            rgb = crop_4x3(np.array(Image.open(SOURCE / "assets" / filename).convert("RGB")))
            self.base_observation[key] = torch.from_numpy(rgb).permute(2, 0, 1).float() / 255

    def predict(self, task: str, camera_npz: str | None = None,
                joint_state: dict | None = None, *, all_actions: bool = False) -> dict[str, Any]:
        torch = self.torch
        # Molmo select_action() drains an internal chunk queue before reading
        # another task. Resetting the warm policy invalidates that queue and
        # its rollout generator, matching synchronous /subtask semantics.
        self.policy.reset()
        self.pre.reset()
        self.post.reset()
        observation = {key: value.clone() for key, value in self.base_observation.items()}
        observation["task"] = task
        if joint_state is not None:
            if not isinstance(joint_state, dict) or set(joint_state) != set(JOINTS):
                raise ValueError("MolmoAct2 live state requires six joints")
            state_values = [float(joint_state[name]) for name in JOINTS]
            if not all(math.isfinite(value) for value in state_values):
                raise ValueError("MolmoAct2 live state must be finite")
            observation["observation.state"] = torch.tensor(state_values, dtype=torch.float32)
        if camera_npz is not None:
            observation.update(load_live_camera_images(camera_npz, torch))
        if all_actions and (camera_npz is None or joint_state is None):
            raise ValueError("Physical prediction requires live cameras and measured joints")

        with torch.inference_mode():
            torch.cuda.synchronize()
            started = time.monotonic()
            actions = self.policy.predict_action_chunk(self.pre(observation))
            torch.cuda.synchronize()
            infer_seconds = round(time.monotonic() - started, 2)
            if tuple(actions.shape) != (1, 30, 6) or not torch.isfinite(actions).all():
                raise RuntimeError("MolmoAct2 did not return a valid 30×6 action block.")
            converted_rows = ([self.post(actions[:, index, :]).squeeze(0).cpu()
                               for index in range(30)] if all_actions else
                              [self.post(actions[:, 0, :]).squeeze(0).cpu()])
            first = converted_rows[0]
            if tuple(first.shape) != (6,) or not torch.isfinite(first).all():
                raise RuntimeError("MolmoAct2 postprocessing returned invalid values.")

        values = [float(value) for value in first]
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError("MolmoAct2 postprocessing returned invalid values.")
        result = {
            "model": "molmoact2",
            "checkpoint": CHECKPOINT,
            "prompt": task,
            "observation": ("live_overhead_x5_measured_joint_state" if all_actions else
                            "live_overhead_x5_sample_joint_state" if camera_npz
                            else "official_sample_top_side"),
            "actionCount": 30,
            "firstAction": dict(zip(JOINTS, values, strict=True)),
            "loadSeconds": self.load_seconds,
            "inferSeconds": infer_seconds,
            "hardwareCommands": False,
            "staleActionsInvalidated": True,
            "inferenceMode": "synchronous_shadow",
        }
        if all_actions:
            if any(tuple(row.shape) != (6,) or not torch.isfinite(row).all()
                   for row in converted_rows):
                raise RuntimeError("MolmoAct2 postprocessing did not return a valid action block.")
            result["actions"] = [dict(zip(JOINTS, (float(v) for v in row), strict=True))
                                 for row in converted_rows]
            result["inferenceMode"] = "live_prediction_pending_guarded_execution"
        return result


def serve(
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
    runtime_factory: Any = MolmoRuntime,
) -> None:
    """Handle multiple tasks in a single process, retaining the loaded model."""
    runtime = None
    sequence = 0
    for line in input_stream:
        try:
            command = json.loads(line)
            if not isinstance(command, dict):
                raise ValueError("JSON command must be an object.")
            op = command.get("op")
            if op == "stop":
                return
            if op == "warm":
                if runtime is None:
                    runtime = runtime_factory()
                output_stream.write("RESULT_JSON:" + json.dumps({"model": "molmoact2",
                    "ready": True, "hardwareCommands": False}) + "\n")
                output_stream.flush()
                continue
            if op not in {"set_task", "predict_chunk"}:
                raise ValueError("Unknown operation; expected warm, set_task, predict_chunk or stop.")
            task = _valid_task(command.get("task"))
            if runtime is None:
                runtime = runtime_factory()
            camera_npz = command.get("camera_npz")
            result = (runtime.predict(task, camera_npz, command.get("state"), all_actions=True)
                      if op == "predict_chunk" else
                      runtime.predict(task, camera_npz) if camera_npz is not None else runtime.predict(task))
            sequence += 1
            result["sequence"] = sequence
            output_stream.write("RESULT_JSON:" + json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
            output_stream.flush()
        except Exception as exc:
            error_stream.write(f"MolmoAct2 session command failed: {type(exc).__name__}: {exc}\n")
            error_stream.flush()
            output_stream.write(
                "ERROR_JSON:" + json.dumps({"error": str(exc), "hardwareCommands": False}, ensure_ascii=False) + "\n"
            )
            output_stream.flush()


if __name__ == "__main__":
    serve()
