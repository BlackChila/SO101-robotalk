"""Optional observer camera, isolated from policy frame synchronization."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2

from camera_profiles import crop_4x3


class OptionalCameraObserver:
    def __init__(self, config: dict):
        self.config = config
        self.name = config.get("label", "Wrist camera")
        self.camera = None
        self.latest = None
        self.error = "Camera not started."
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = None

    @property
    def available(self) -> bool:
        with self.condition:
            return self.camera is not None and self.error is None and not self.stop_event.is_set()

    def start(self) -> None:
        from flux3_scene_setup import apply_controls

        self.close()
        self.stop_event.clear()
        try:
            if not Path(self.config["path"]).exists():
                raise RuntimeError(f"{self.name} is not connected.")
            if self.config.get("controls"):
                apply_controls(self.config)
            self.camera = cv2.VideoCapture(self.config["path"], cv2.CAP_V4L2)
            if not self.camera.isOpened():
                raise RuntimeError(f"{self.name} could not be opened.")
            self.camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config["width"])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config["height"])
            self.camera.set(cv2.CAP_PROP_FPS, self.config.get("fps", 30))
            frame = None
            for _ in range(15):
                ok, candidate = self.camera.read()
                captured_at = time.monotonic()
                if ok and self._valid(candidate):
                    frame = candidate
                    frame_captured_at = captured_at
            if frame is None:
                raise RuntimeError(f"{self.name} is not providing a valid image.")
            with self.condition:
                self.latest = (cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), frame_captured_at)
                self.error = None
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
        except Exception as exc:
            self.close()
            self.error = str(exc)

    def _valid(self, frame) -> bool:
        return frame is not None and frame.shape == (self.config["height"], self.config["width"], 3)

    def _capture_loop(self) -> None:
        try:
            while not self.stop_event.is_set():
                ok, frame = self.camera.read()
                captured_at = time.monotonic()
                if not ok or not self._valid(frame):
                    raise RuntimeError(f"No valid image: {self.name}.")
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self.condition:
                    self.latest = (rgb, captured_at)
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                if not self.stop_event.is_set():
                    self.error = str(exc)
                self.condition.notify_all()

    def snapshot(self, *, after: float = 0.0, timeout_s: float = 0.8, raw: bool = False,
                 with_meta: bool = False):
        deadline = time.monotonic() + timeout_s
        with self.condition:
            while True:
                if not self.available:
                    if after:
                        raise RuntimeError(self.error or f"{self.name} is not ready.")
                    return None
                if self.latest:
                    rgb, timestamp = self.latest
                    if timestamp > after and time.monotonic() - timestamp <= 0.5:
                        crop = self.config.get("crop")
                        image = (rgb if raw or crop is None else crop_4x3(
                            rgb, crop,
                            expected_wh=(self.config["width"], self.config["height"]))).copy()
                        return (image, timestamp) if with_meta else image
                if not after:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"No fresh image: {self.name}.")
                self.condition.wait(min(remaining, 0.05))

    def close(self) -> None:
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=1)
            self.thread = None
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        self.latest = None
