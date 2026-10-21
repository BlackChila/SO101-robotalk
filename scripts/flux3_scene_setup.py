"""Prepare and inspect the three cameras used by SO-101 conversations.

This shared module never opens the robot or a serial port. Its historical
filename is retained for camera-worker and installation compatibility.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import math

from camera_profiles import CAPTURE_CAMERAS, camera_profile
from copy import deepcopy


ROOT = Path(__file__).resolve().parents[1]

OVERHEAD = deepcopy(CAPTURE_CAMERAS["scene"])
WRIST = deepcopy(CAPTURE_CAMERAS["wrist"])

INSTA360 = {
    "path": "/dev/v4l/by-id/usb-Insta_Insta360_X5_0001-video-index0",
    "width": 2880,
    "height": 1440,
    # Rectilinear view from the 2:1 equirectangular USB stream. This points at
    # the same task region visible in the model scene camera.
    "perspective": {"yaw_deg": -22.0, "pitch_deg": -38.0,
                    "horizontal_fov_deg": 70.0, "width": 640, "height": 480},
}

OUTPUTS = {
    "overhead": ROOT / "outputs/current-overhead.jpg",
    "wrist": ROOT / "outputs/current-wrist.jpg",
    "insta360": ROOT / "outputs/current-insta360.jpg",
}


def _control_argument(controls: dict[str, int]) -> str:
    return ",".join(f"{name}={value}" for name, value in controls.items())


def apply_controls(config: dict) -> None:
    subprocess.run(
        ["v4l2-ctl", "--device", config["path"], "--set-ctrl",
         _control_argument(config["controls"])],
        check=True,
    )


def apply_camera_controls() -> None:
    """Apply the fixed overhead and wrist camera controls before capture."""
    apply_controls(OVERHEAD)
    apply_controls(WRIST)


def _validated_crop(frame: np.ndarray, crop: tuple[int, int, int, int]) -> np.ndarray:
    x, y, width, height = crop
    if min(x, y, width, height) < 0 or x + width > frame.shape[1] or y + height > frame.shape[0]:
        raise ValueError(f"Crop {crop} does not fit frame {frame.shape[:2]}")
    result = frame[y:y + height, x:x + width]
    if result.shape[:2] != (height, width):
        raise RuntimeError(f"Unexpected crop result {result.shape}")
    return result


def equirectangular_to_perspective(
    frame: np.ndarray, *, yaw_deg: float, pitch_deg: float,
    horizontal_fov_deg: float, width: int, height: int,
) -> np.ndarray:
    """Project a 2:1 equirectangular frame into a normal perspective view."""
    if frame.shape[1] != frame.shape[0] * 2:
        raise ValueError(f"Expected a 2:1 equirectangular frame, got {frame.shape[:2]}")
    if not (0 < horizontal_fov_deg < 180 and width > 0 and height > 0):
        raise ValueError("Invalid perspective projection settings")
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    hfov = math.radians(horizontal_fov_deg)
    vfov = 2 * math.atan(math.tan(hfov / 2) * height / width)
    x = ((np.arange(width) + 0.5 - width / 2) / (width / 2)) * math.tan(hfov / 2)
    y = -((np.arange(height) + 0.5 - height / 2) / (height / 2)) * math.tan(vfov / 2)
    nx, ny = np.meshgrid(x, y)
    forward = np.array([math.cos(pitch) * math.sin(yaw), math.sin(pitch),
                        math.cos(pitch) * math.cos(yaw)])
    right = np.array([math.cos(yaw), 0.0, -math.sin(yaw)])
    up = np.cross(forward, right)
    rays = forward + nx[..., None] * right + ny[..., None] * up
    rays /= np.linalg.norm(rays, axis=2, keepdims=True)
    longitude = np.arctan2(rays[..., 0], rays[..., 2])
    latitude = np.arcsin(rays[..., 1])
    map_x = ((longitude / (2 * math.pi) + 0.5) * frame.shape[1]).astype(np.float32)
    map_y = ((0.5 - latitude / math.pi) * frame.shape[0]).astype(np.float32)
    return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def capture(config: dict, *, warmup_frames: int = 60) -> np.ndarray:
    cap = cv2.VideoCapture(config["path"], cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {config['path']}")
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["height"])
        cap.set(cv2.CAP_PROP_FPS, 30)
        frame = None
        for _ in range(warmup_frames):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"Cannot capture {config['path']}")
        expected = (config["height"], config["width"], 3)
        if frame is None or frame.shape != expected:
            raise RuntimeError(f"Expected frame {expected}, got {None if frame is None else frame.shape}")
        if config.get("crop") is not None:
            frame = _validated_crop(frame, config["crop"])
        if config.get("perspective") is not None:
            frame = equirectangular_to_perspective(frame, **config["perspective"])
        return frame
    finally:
        cap.release()


def capture_visible(config: dict, *, attempts: int = 3, warmup_frames: int = 60) -> np.ndarray:
    """Retry cameras such as the X5 that may emit black frames after USB open."""
    last = None
    for attempt in range(attempts):
        last = capture(config, warmup_frames=warmup_frames)
        if luminance_metrics(last)["mean"] >= 2.0:
            return last
        if attempt + 1 < attempts:
            time.sleep(0.25)
    raise RuntimeError(f"{config['path']} remained black after {attempts} capture attempts")


def luminance_metrics(frame: np.ndarray) -> dict[str, float]:
    luminance = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return {
        "mean": round(float(luminance.mean()), 2),
        "p05": round(float(np.percentile(luminance, 5)), 2),
        "p50": round(float(np.percentile(luminance, 50)), 2),
        "p95": round(float(np.percentile(luminance, 95)), 2),
        "dark_fraction": round(float(np.mean(luminance < 32)), 4),
        "clipped_fraction": round(float(np.mean(luminance >= 250)), 4),
    }


def exposure_ok(role: str, metrics: dict[str, float]) -> bool:
    limits = {
        "overhead": (35.0, 160.0, 0.35, 0.05),
        "wrist": (35.0, 200.0, 0.45, 0.10),
        "insta360": (45.0, 210.0, 0.35, 0.10),
    }
    low, high, max_dark, max_clipped = limits[role]
    return (low <= metrics["mean"] <= high
            and metrics["dark_fraction"] <= max_dark
            and metrics["clipped_fraction"] <= max_clipped)


def run_scene_setup() -> dict:
    apply_camera_controls()
    frames = {
        "overhead": capture(OVERHEAD),
        "wrist": capture(WRIST),
        "insta360": capture_visible(INSTA360, warmup_frames=120),
    }
    OUTPUTS["overhead"].parent.mkdir(parents=True, exist_ok=True)
    report = {"captured_at_unix": time.time(), "camera_roles": {
        "overhead": "conversation overhead camera",
        "wrist": "conversation wrist camera",
        "insta360": "operator observation only",
    }, "camera_profile": camera_profile("conversation"), "insta360_projection": INSTA360["perspective"], "cameras": {}}
    for role, frame in frames.items():
        if not cv2.imwrite(str(OUTPUTS[role]), frame):
            raise RuntimeError(f"Cannot write {OUTPUTS[role]}")
        metrics = luminance_metrics(frame)
        report["cameras"][role] = {
            "path": (OVERHEAD if role == "overhead" else WRIST if role == "wrist" else INSTA360)["path"],
            "image": str(OUTPUTS[role]),
            "shape": list(frame.shape),
            "luminance": metrics,
            "exposure_ok": exposure_ok(role, metrics),
        }
    report["automatic_checks_pass"] = all(item["exposure_ok"] for item in report["cameras"].values())
    report_path = ROOT / "outputs/scene-setup.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_scene_setup()
    print(json.dumps(report, indent=2))
    if not report["automatic_checks_pass"]:
        raise SystemExit("Automatic exposure check failed; inspect images before starting conversation motion")


if __name__ == "__main__":
    main()
