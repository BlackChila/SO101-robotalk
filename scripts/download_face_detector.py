#!/usr/bin/env python3
"""Explicitly install the small OpenCV 4.x YuNet model, with pinned integrity."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import tempfile
import urllib.request

MODEL_PATH = Path(__file__).resolve().parents[1] / "models/face-tracking/face_detection_yunet_2023mar.onnx"
MODEL_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
# Published Git LFS object digest in the official OpenCV Zoo repository.
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_SIZE = 232589


def verify_model(path: Path) -> None:
    if path.stat().st_size != MODEL_SIZE or hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("YuNet model checksum mismatch; run scripts/download_face_detector.py again.")


def download_model(destination: Path = MODEL_PATH) -> Path:
    destination = Path(destination)
    if destination.is_file():
        try:
            verify_model(destination)
            return destination
        except ValueError:
            pass
    with urllib.request.urlopen(MODEL_URL, timeout=30) as response:
        data = response.read(MODEL_SIZE + 1)
    if len(data) != MODEL_SIZE or hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise ValueError("Downloaded YuNet model failed its pinned size/checksum check.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        temporary.replace(destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=MODEL_PATH)
    print(download_model(parser.parse_args().output))
