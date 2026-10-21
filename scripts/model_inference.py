"""Registry and validated results for warm, hardware-free policy sessions."""

from __future__ import annotations

import math

from camera_profiles import camera_profile
from model_sessions import ROOT, session

MOLMO_PYTHON = ROOT / "environments" / "molmoact2" / ".venv" / "bin" / "python"
MOLMO_WORKER = ROOT / "scripts" / "molmoact2_session.py"
MOLMO_RUNTIME = ROOT / "models" / "molmoact2" / "runtime"
MOLMO_SOURCE = ROOT / "models" / "molmoact2" / "source"
JOINTS = {"shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"}


def molmo_blocker() -> str | None:
    required = (
        MOLMO_PYTHON,
        MOLMO_WORKER,
        MOLMO_RUNTIME / "config.json",
        MOLMO_RUNTIME / "model.safetensors",
        MOLMO_SOURCE / "config.json",
        MOLMO_SOURCE / "assets" / "sample_realsense_top_rgb.png",
        MOLMO_SOURCE / "assets" / "sample_realsense_side_rgb.png",
    )
    if not all(path.is_file() for path in required):
        return "The MolmoAct2 environment, checkpoint or sample images are missing."
    return None


def models(*, cuda_available: bool = True) -> list[dict]:
    cuda_blocker = None if cuda_available else "CUDA is not available."
    molmo = molmo_blocker() or cuda_blocker
    return [
        {"id": "molmoact2", "label": "MolmoAct2", "available": molmo is None,
         "cameraProfile": camera_profile("molmoact2"),
         "message": molmo or "MolmoAct2 for conversation tasks with live cameras and measured joint positions."},
    ]


def infer(model_id: str, prompt: str, *, camera_npz: str | None = None) -> dict:
    blockers = {"molmoact2": molmo_blocker}
    if model_id not in blockers:
        raise ValueError("Unknown model.")
    blocker = blockers[model_id]()
    if blocker:
        raise RuntimeError(blocker)
    result = (session.set_task(model_id, prompt, camera_npz=camera_npz)
              if camera_npz is not None else session.set_task(model_id, prompt))
    first = result.get("firstAction")
    if (result.get("hardwareCommands") is not False or result.get("model") != model_id
            or not isinstance(result.get("actionCount"), int)
            or not 0 < result["actionCount"] <= 256 or not isinstance(first, dict)
            or set(first) != JOINTS
            or not all(isinstance(value, (int, float)) and math.isfinite(value)
                       for value in first.values())):
        session.stop()
        raise RuntimeError("Invalid model result report.")
    return result


def predict_physical_chunk(model_id: str, prompt: str, *, observation_npz: str,
                           state: dict) -> dict:
    """Validate a live prediction before the separate motor owner sees it."""
    if model_id not in {"molmoact2"}:
        raise ValueError("Unknown model.")
    result = session.predict_chunk(model_id, prompt, observation_npz=observation_npz, state=state)
    actions = result.get("actions")
    if (result.get("model") != model_id or result.get("hardwareCommands") is not False
            or not isinstance(actions, list) or not 1 <= len(actions) <= 32
            or result.get("actionCount") != len(actions)
            or any(not isinstance(action, dict) or set(action) != JOINTS
                   or any(isinstance(value, bool) or not isinstance(value, (int, float))
                          or not math.isfinite(value) for value in action.values())
                   for action in actions)):
        session.stop()
        raise RuntimeError("Invalid action block from the selected model.")
    return result
