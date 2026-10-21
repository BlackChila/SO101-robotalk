#!/usr/bin/env python3
"""Run one MolmoAct2 SO-101 prediction on the official sample, without hardware."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from camera_profiles import crop_4x3

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "models" / "molmoact2" / "runtime"
SOURCE = ROOT / "models" / "molmoact2" / "source"
JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def predict(prompt: str) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.molmoact2.modeling_molmoact2 import MolmoAct2Policy

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable for MolmoAct2.")
    config = PreTrainedConfig.from_pretrained(RUNTIME)
    config.checkpoint_path = str(SOURCE)
    config.device = "cuda"
    config.push_to_hub = False
    config.enable_inference_cuda_graph = False
    if config.image_keys != ["observation.images.cam0", "observation.images.cam1"]:
        raise RuntimeError(f"Unexpected camera inputs: {config.image_keys}")
    if config.chunk_size != 30:
        raise RuntimeError(f"Unexpected action length: {config.chunk_size}")

    torch.manual_seed(0)
    started = time.monotonic()
    policy = MolmoAct2Policy.from_pretrained(RUNTIME, config=config).eval()
    pre, post = make_pre_post_processors(
        config, pretrained_path=str(RUNTIME),
        preprocessor_overrides={
            "molmoact2_pack_inputs": {"checkpoint_path": str(SOURCE)},
            "device_processor": {"device": "cuda"},
        },
        postprocessor_overrides={"device_processor": {"device": "cpu"}},
    )
    load_seconds = time.monotonic() - started

    # The official example state uses the historical joint frame. Convert it
    # back once; the saved LeRobot processor applies its own correction.
    sample_state = torch.tensor(
        [-0.52734375, 189.140625, 181.40625, 60.64453125, -3.603515625, 1.0971786975860596]
    )
    state = (sample_state - torch.tensor(config.joint_offsets)) / torch.tensor(config.joint_signs)
    observation = {"observation.state": state, "task": prompt}
    for key, filename in zip(config.image_keys, (
        "sample_realsense_top_rgb.png", "sample_realsense_side_rgb.png"
    ), strict=True):
        rgb = crop_4x3(np.array(Image.open(SOURCE / "assets" / filename).convert("RGB")))
        observation[key] = torch.from_numpy(rgb).permute(2, 0, 1).float() / 255

    with torch.inference_mode():
        policy.reset()
        pre.reset()
        post.reset()
        torch.cuda.synchronize()
        started = time.monotonic()
        actions = policy.predict_action_chunk(pre(observation))
        torch.cuda.synchronize()
        infer_seconds = time.monotonic() - started
        if tuple(actions.shape) != (1, 30, 6) or not torch.isfinite(actions).all():
            raise RuntimeError("MolmoAct2 did not return a valid 30×6 action block.")
        first = post(actions[:, 0, :]).squeeze(0).cpu()
        if tuple(first.shape) != (6,) or not torch.isfinite(first).all():
            raise RuntimeError("MolmoAct2 postprocessing returned invalid values.")

    return {
        "model": "molmoact2",
        "checkpoint": "lerobot/MolmoAct2-SO100_101-LeRobot",
        "prompt": prompt,
        "observation": "official_sample_top_side",
        "actionCount": 30,
        "firstAction": dict(zip(JOINTS, (float(value) for value in first), strict=True)),
        "loadSeconds": round(load_seconds, 2),
        "inferSeconds": round(infer_seconds, 2),
        "hardwareCommands": False,
    }


def main() -> None:
    request = json.load(sys.stdin)
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 500:
        raise ValueError("The prompt must contain 1 to 500 characters.")
    print("RESULT_JSON:" + json.dumps(predict(prompt.strip()), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
