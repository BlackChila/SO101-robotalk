"""Local latest-frame YuNet worker. Never opens a camera or motor connection."""
from __future__ import annotations

import base64
import math
from pathlib import Path
import threading
import time

import cv2
import numpy as np

from download_face_detector import MODEL_PATH, verify_model
from face_tracking_control import TRACKING_TARGET_X, TRACKING_TARGET_Y


def upright_frame(rgb: np.ndarray, max_side: int = 640) -> np.ndarray:
    """Return an upright BGR detector image without changing the camera stream."""
    upright = cv2.rotate(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), cv2.ROTATE_90_CLOCKWISE)
    height, width = upright.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale < 1:
        upright = cv2.resize(upright, (round(width * scale), round(height * scale)),
                             interpolation=cv2.INTER_AREA)
    return upright


class FaceAssociation:
    """Keep a nearby face across frames; briefly resist switching to a bystander."""
    def __init__(self, retention_s: float = 1.0):
        self.box = None
        self.last_seen = 0.0
        self.retention_s = retention_s

    def select(self, faces, width: int, height: int, captured_at: float):
        candidates = []
        for face in [] if faces is None else faces:
            if len(face) < 15 or not np.isfinite(face).all() or face[2] <= 0 or face[3] <= 0:
                continue
            x, y, w, h = [float(value) for value in face[:4]]
            left, top = max(0.0, x / width), max(0.0, y / height)
            right, bottom = min(1.0, (x + w) / width), min(1.0, (y + h) / height)
            if right <= left or bottom <= top:
                continue
            candidates.append({"box": (left, top, right, bottom), "confidence": float(face[-1])})
        if self.box is not None and captured_at - self.last_seen > self.retention_s:
            self.box = None
        selected = None
        if self.box is not None:
            a = self.box
            ranked = []
            for candidate in candidates:
                b = candidate["box"]
                intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
                area_a, area_b = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
                iou = intersection / (area_a + area_b - intersection)
                distance = math.hypot((a[0] + a[2] - b[0] - b[2]) / 2,
                                      (a[1] + a[3] - b[1] - b[3]) / 2)
                if iou >= 0.1 or (distance <= 0.15 and 0.4 <= area_b / area_a <= 2.5):
                    ranked.append((iou - distance, candidate))
            if ranked:
                selected = max(ranked, key=lambda item: item[0])[1]
        elif candidates:
            selected = max(candidates, key=lambda item: (item["box"][2] - item["box"][0]) *
                           (item["box"][3] - item["box"][1]) * item["confidence"])
        if selected:
            self.box = selected["box"]
            self.last_seen = captured_at
        return selected


class FaceDetectionWorker:
    def __init__(self, observer, model_path: Path = MODEL_PATH):
        self.observer = observer
        self.model_path = Path(model_path)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._detector = None
        self._sequence = 0
        self._observation = None
        self._preview = None
        self._state = "stopped"
        self._error = None

    def _availability_error(self):
        if self.observer is None or not self.observer.available:
            return "Wrist camera is not available."
        if not self.model_path.is_file():
            return "YuNet model missing. Run: python scripts/download_face_detector.py"
        if not hasattr(cv2, "FaceDetectorYN"):
            return "OpenCV FaceDetectorYN is not installed in the camera environment."
        return None

    def start(self) -> dict:
        if self._thread and self._thread.is_alive():
            return self.status()
        error = self._availability_error()
        if error:
            raise RuntimeError(error)
        verify_model(self.model_path)
        self._detector = cv2.FaceDetectorYN.create(
            str(self.model_path), "", (320, 320), 0.8, 0.3, 5000,
            cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU)
        self._stop.clear()
        with self._lock:
            self._observation = self._preview = None
            self._error = None
            self._state = "starting"
        self._thread = threading.Thread(target=self._run, name="wrist-face-detection", daemon=True)
        self._thread.start()
        return self.status()

    def _run(self):
        association = FaceAssociation()
        after = 0.0
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                snapshot = self.observer.snapshot(after=after, raw=True, with_meta=True, timeout_s=0.4)
                if snapshot is None:
                    raise RuntimeError("No fresh wrist frame.")
                rgb, captured_at = snapshot
                if captured_at <= after or not 0 <= time.monotonic() - captured_at <= 0.5:
                    raise RuntimeError("Stale wrist frame.")
                after = captured_at
                frame = upright_frame(rgb)
                height, width = frame.shape[:2]
                self._detector.setInputSize((width, height))
                _, faces = self._detector.detect(frame)
                selected = association.select(faces, width, height, captured_at)
                self._sequence += 1
                observation = {"sequence": self._sequence, "captured_at": captured_at,
                               "detected": selected is not None, "x": 0.5, "y": 0.5, "confidence": 0.0}
                if selected:
                    left, top, right, bottom = selected["box"]
                    observation.update(x=(left + right) / 2, y=(top + bottom) / 2,
                                       confidence=selected["confidence"])
                    cv2.rectangle(frame, (int(left * width), int(top * height)),
                                  (int(right * width), int(bottom * height)), (80, 205, 110), 2)
                target = (round(width * TRACKING_TARGET_X), round(height * TRACKING_TARGET_Y))
                cv2.drawMarker(frame, target, (255, 220, 80),
                               cv2.MARKER_CROSS, 16, 1)
                ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                preview = {"jpeg": base64.b64encode(jpeg).decode(), "width": width, "height": height} if ok else None
                with self._lock:
                    self._observation = observation
                    self._preview = preview
                    self._state = "detected" if selected else "searching"
                self._stop.wait(max(0, 1 / 15 - (time.monotonic() - started)))
        except Exception as exc:
            if not self._stop.is_set():
                with self._lock:
                    self._error = str(exc)
                    self._state = "fault"
                    self._observation = self._preview = None

    def status(self) -> dict:
        with self._lock:
            availability_error = self._availability_error()
            return {"available": availability_error is None, "running": bool(self._thread and self._thread.is_alive()),
                    "state": self._state, "error": self._error or availability_error,
                    "rotation_degrees": 90,
                    "observation": dict(self._observation) if self._observation else None,
                    "preview": dict(self._preview) if self._preview else None}

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError("Face detector did not stop; camera worker restart required.")
        self._thread = self._detector = None
        with self._lock:
            self._state = "stopped"
            self._observation = self._preview = None
            self._error = None
        return self.status()
