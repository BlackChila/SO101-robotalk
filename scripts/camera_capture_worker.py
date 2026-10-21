#!/usr/bin/env python3
"""Camera-only worker for the speech UI. Never opens the robot serial bus."""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from camera_profiles import camera_profile, crop_4x3
from camera_observer import OptionalCameraObserver
from realtime_scene import encode_scene_image
from face_detection import FaceDetectionWorker
from insta360_view import DEFAULT_VIEW, projection_filter, save_view, validate_view
from camera_brightness import load_brightness, probe_brightness, save_brightness, set_brightness
from camera_exposure import load_exposure, probe_exposure, save_exposure, set_exposure, validate_exposure
from shared_camera_stream import SOCKET_PATH, receive_packet, send_packet

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "outputs" / "ui-camera-inputs"


def project_x5(rgb: np.ndarray, filter_spec: str) -> np.ndarray:
    if rgb.shape != (1440, 2880, 3) or rgb.dtype != np.uint8:
        raise ValueError(f"Expected X5 RGB panorama 2880x1440, got {rgb.shape}")
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "2",
         "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "2880x1440",
         "-i", "pipe:0", "-filter_threads", "2", "-vf", filter_spec,
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        input=rgb.tobytes(), capture_output=True, timeout=5, check=True,
    )
    if len(result.stdout) != 960 * 720 * 3:
        raise RuntimeError("Incomplete X5 perspective image.")
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(720, 960, 3).copy()


class CameraPair:
    def __init__(self, model_id: str):
        self.profile = camera_profile(model_id)
        self.model_id = model_id
        self.observers = {role: OptionalCameraObserver(config)
                          for role, config in self.profile.get("observer_cameras", {}).items()}
        self.cameras: dict[str, cv2.VideoCapture] = {}
        self.latest: dict[str, tuple[np.ndarray, float]] = {}
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.capture_error: str | None = None
        self.failed_roles: set[str] = set()
        self.brightness: dict[str, dict | None] = {}
        self.exposure: dict[str, dict | None] = {}
        self.adjusting_exposure: set[str] = set()
        self.face_detector = None

    def face_tracking(self, action: str = "status") -> dict:
        if action not in {"start", "stop", "status"}:
            raise ValueError("Unknown face tracking action.")
        if self.model_id not in {"conversation", "molmoact2"}:
            raise ValueError("Face tracking requires the conversation or MolmoAct2 camera profile.")
        if self.face_detector is None:
            self.face_detector = FaceDetectionWorker(self.observers.get("wrist"))
        return getattr(self.face_detector, action)()

    def connect(self) -> None:
        if self.model_id == "conversation":
            for observer in self.observers.values():
                observer.start()
            return
        if self.model_id == "molmoact2":
            self._connect_molmo()
            return
        raise ValueError("Unknown camera profile.")

    def _connect_molmo(self) -> None:
        """Keep the two model slots, using one fresh source when a camera is absent."""
        from flux3_scene_setup import apply_controls

        errors = {}
        for role, config in self.profile["cameras"].items():
            device = Path(config["path"])
            if not device.exists():
                errors[role] = f"{role} is not connected: {device}"
                continue
            try:
                if role == "cam0":
                    apply_controls(config)
                for _ in range(3):
                    camera = cv2.VideoCapture(str(device), cv2.CAP_V4L2)
                    try:
                        if not camera.isOpened():
                            errors[role] = f"{role} could not be opened: {device}"
                            continue
                        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                        camera.set(cv2.CAP_PROP_FRAME_WIDTH, config["width"])
                        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config["height"])
                        camera.set(cv2.CAP_PROP_FPS, 30)
                        for _ in range(120):
                            ok, frame = camera.read()
                            if (ok and frame is not None and
                                    frame.shape == (config["height"], config["width"], 3) and
                                    frame[::16, ::16].mean() >= 2):
                                self.cameras[role] = camera
                                break
                        if role in self.cameras:
                            break
                        errors[role] = f"{role} is not providing a visible image: {device}"
                    finally:
                        if role not in self.cameras:
                            camera.release()
            except Exception as exc:
                errors[role] = f"{role}: {exc}"
        if not self.cameras:
            raise RuntimeError("No MolmoAct2 camera is ready: " + "; ".join(errors.values()))
        for observer in self.observers.values():
            observer.start()
        self.start_streaming()

    def read_raw(self) -> dict[str, np.ndarray]:
        frames = {}
        for role, camera in self.cameras.items():
            ok, frame = camera.read()
            config = self.profile["cameras"][role]
            if not ok or frame is None or frame.shape != (config["height"], config["width"], 3):
                raise RuntimeError(f"No valid image from {role}.")
            frames[role] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return frames

    def start_streaming(self) -> None:
        self.stop_event.clear()
        for role, camera in self.cameras.items():
            thread = threading.Thread(target=self._capture_loop, args=(role, camera), daemon=True)
            thread.start()
            self.threads.append(thread)

    def _capture_loop(self, role: str, camera: cv2.VideoCapture) -> None:
        config = self.profile["cameras"][role]
        try:
            while not self.stop_event.is_set():
                ok, bgr = camera.read()
                timestamp = time.monotonic()
                if not ok or bgr is None or bgr.shape != (config["height"], config["width"], 3):
                    raise RuntimeError(f"No valid image from {role}.")
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                if self.model_id == "molmoact2" and role not in self.adjusting_exposure and rgb[::16, ::16].mean() < 2:
                    raise RuntimeError(f"Camera {role} is providing a black image.")
                with self.condition:
                    self.latest[role] = (rgb, timestamp)
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                if self.model_id == "molmoact2":
                    self.failed_roles.add(role)
                    if len(self.failed_roles) == len(self.cameras):
                        self.capture_error = f"No MolmoAct2 camera remains ready: {exc}"
                else:
                    self.capture_error = str(exc)
                self.condition.notify_all()

    def fresh_raw(self, *, after: float = 0.0, timeout_s: float = 0.8) -> tuple[dict, dict]:
        deadline = time.monotonic() + timeout_s
        with self.condition:
            while True:
                if self.capture_error:
                    raise RuntimeError(self.capture_error)
                active_roles = self.cameras.keys() - self.failed_roles
                if not active_roles:
                    raise RuntimeError("No cameras remain ready.")
                if active_roles <= self.latest.keys():
                    timestamps = {role: self.latest[role][1] for role in active_roles}
                    now = time.monotonic()
                    if (all(stamp > after and now - stamp <= 0.2 for stamp in timestamps.values())
                            and max(timestamps.values()) - min(timestamps.values()) <= 0.08):
                        return ({role: self.latest[role][0].copy() for role in active_roles},
                                timestamps)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("No fresh synchronized camera pair.")
                self.condition.wait(min(remaining, 0.05))

    def read_views(self, *, after: float = 0.0, with_meta: bool = False,
                   timeout_s: float = 0.8):
        if self.threads:
            raw, timestamps = self.fresh_raw(after=after, timeout_s=timeout_s)
        else:
            raw, timestamps = self.read_raw(), {}
        views = {}
        for role, rgb in raw.items():
            config = self.profile["cameras"][role]
            if role == "cam1":
                rgb = project_x5(rgb, self.profile["x5_projection"])
            if self.profile["geometry"] == "highres_4x3" or self.model_id == "molmoact2":
                rgb = crop_4x3(rgb, config["crop"] if role != "cam1" else None)
            if rgb[::16, ::16].mean() < 2:
                raise RuntimeError(f"Camera {role} is providing a black image.")
            views[role] = rgb.copy()
        if self.model_id == "molmoact2" and len(views) == 1:
            source = next(iter(views))
            missing = "cam1" if source == "cam0" else "cam0"
            views[missing] = views[source].copy()
            if source in timestamps:
                timestamps[missing] = timestamps[source]
        return (views, timestamps) if with_meta else views

    def camera_sources(self) -> dict[str, str]:
        with self.condition:
            active = self.cameras.keys() - self.failed_roles
        if self.model_id == "molmoact2" and len(active) == 1:
            source = next(iter(active))
            return {"cam0": source, "cam1": source}
        return {role: role for role in self.profile["cameras"]}

    @staticmethod
    def previews(views: dict[str, np.ndarray]) -> dict[str, dict]:
        result = {}
        for role, rgb in views.items():
            # A JPEG preview is display-only. Inference receives the exact RGB
            # crop above, before the checkpoint's own resize.
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                raise RuntimeError(f"The preview for {role} could not be encoded.")
            result[role] = {"width": rgb.shape[1], "height": rgb.shape[0],
                            "jpeg": base64.b64encode(encoded).decode("ascii")}
        return result

    def capture(self) -> dict:
        if self.model_id == "conversation":
            raise ValueError("Conversation cameras provide previews only.")
        count = 1
        frames = {role: [] for role in self.profile["cameras"]}
        after = 0.0
        for index in range(count):
            views, timestamps = self.read_views(after=after, with_meta=True)
            for role, rgb in views.items():
                frames[role].append(rgb)
            after = max(timestamps.values()) if timestamps else after
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=f"{self.model_id}-", suffix=".npz",
                                         dir=SNAPSHOT_DIR, delete=False) as output:
            path = Path(output.name)
            np.savez(output, **{role: np.stack(images) for role, images in frames.items()})
        return {"model": self.model_id, "path": str(path), "frames": count,
                "previews": self.previews(views), "capturedAt": time.time(),
                "geometry": self.profile["geometry"], "cameraSources": self.camera_sources(),
                "insta360View": self.insta360_view(), "cameraBrightness": self.brightness_metadata(), "cameraExposure": self.exposure_metadata()}

    def initialize_brightness(self) -> None:
        saved = load_brightness()
        for role in self.active_camera_roles():
            device = self.camera_config(role)["path"]
            try:
                control = probe_brightness(device)
                if control is not None and device in saved:
                    control = set_brightness(device, saved[device], control)
                self.brightness[role] = control
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                self.brightness[role] = None
                print(f"Brightness control for {role} is not ready: {exc}", file=sys.stderr, flush=True)

    def brightness_metadata(self) -> dict:
        return {role: self.brightness.get(role) for role in self.active_camera_roles()}

    def camera_config(self, role: str) -> dict:
        return (self.profile["cameras"][role] if role in self.profile["cameras"]
                else self.profile["observer_cameras"][role])

    def active_camera_roles(self) -> set[str]:
        with self.condition:
            active = self.cameras.keys() - self.failed_roles
        return active | {role for role, observer in self.observers.items() if observer.available}

    def observer_previews(self, *, after: float = 0.0, role: str | None = None) -> dict:
        result = {}
        for observer_role, observer in self.observers.items():
            target_after = after if role in (None, observer_role) else 0.0
            try:
                panorama = self.model_id == "conversation" and observer_role == "cam1"
                frame = observer.snapshot(after=target_after, raw=True) if panorama else observer.snapshot(after=target_after)
                if frame is not None:
                    if panorama:
                        frame = project_x5(frame, self.profile["x5_projection"])
                    result.update(self.previews({observer_role: frame}))
            except Exception:
                # Optional display failures cannot invalidate the model cameras.
                # A manual setting still needs a fresh observer image to commit.
                if target_after:
                    raise
        return result

    def observer_status(self) -> dict:
        return {role: {"connected": observer.available, "message": observer.error}
                for role, observer in self.observers.items()}

    def settings_preview(self, role: str) -> dict:
        after = time.monotonic() + 0.4
        return (self.preview(observer_after=after, observer_role=role) if role in self.observers
                else self.preview(after=after))

    def set_camera_brightness(self, role: str, value: int) -> dict:
        control = self.brightness_metadata().get(role)
        if control is None:
            raise RuntimeError("This camera has no available brightness control.")
        device = self.camera_config(role)["path"]
        # Read the actual current setting so rollback also preserves external adjustments.
        previous = probe_brightness(device)
        if previous is None:
            raise RuntimeError("Brightness control is no longer available.")
        from camera_brightness import validate_brightness
        validate_brightness(value, previous)
        try:
            self.brightness[role] = set_brightness(device, value, previous)
            result = self.settings_preview(role)
            save_brightness(device, value)
            return result
        except Exception as exc:
            try:
                self.brightness[role] = set_brightness(device, previous["value"], previous)
            except Exception as rollback_error:
                self.brightness[role] = None
                raise RuntimeError(f"Brightness was not saved; rollback was not confirmed: {rollback_error}") from exc
            raise

    def initialize_exposure(self) -> None:
        saved = load_exposure()
        for role in self.active_camera_roles():
            device = self.camera_config(role)["path"]
            try:
                control = probe_exposure(device)
                if control is not None and device in saved:
                    control = set_exposure(device, saved[device], control)
                self.exposure[role] = self._exposure_default(role, control)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                self.exposure[role] = None
                print(f"Exposure control for {role} is not ready: {exc}", file=sys.stderr, flush=True)

    def _exposure_default(self, role: str, control: dict | None) -> dict | None:
        if control is None:
            return None
        baseline = self.camera_config(role).get("controls", {}).get("exposure_time_absolute")
        return {**control, "default": baseline if baseline is not None else control["default"]}

    def exposure_metadata(self) -> dict:
        return {role: self.exposure.get(role) for role in self.active_camera_roles()}

    def set_camera_exposure(self, role: str, value: int) -> dict:
        if self.exposure_metadata().get(role) is None:
            raise RuntimeError("This camera has no available exposure control.")
        device = self.camera_config(role)["path"]
        previous = probe_exposure(device)
        if previous is None:
            raise RuntimeError("Exposure control is no longer available.")
        validate_exposure(value, previous)
        self.adjusting_exposure.add(role)
        try:
            self.exposure[role] = self._exposure_default(role, set_exposure(device, value, previous))
            # USB buffers can still contain sensor frames from the old shutter.
            result = self.settings_preview(role)
            if result.get("cameraExposure", {}).get(role) is None:
                raise RuntimeError("The camera failed while changing exposure.")
            save_exposure(device, value)
            return result
        except Exception as exc:
            try:
                self.exposure[role] = self._exposure_default(role, set_exposure(device, previous["value"], previous))
                # Keep dark transitional frames from disabling a Molmo source until
                # the restored shutter has produced a valid fresh image.
                restored = self.settings_preview(role)
                if restored.get("cameraExposure", {}).get(role) is None:
                    raise RuntimeError("The camera is not providing a confirmed recovery image.")
            except Exception as rollback_error:
                self.exposure[role] = None
                raise RuntimeError(f"Exposure was not saved; rollback was not confirmed: {rollback_error}") from exc
            raise
        finally:
            self.adjusting_exposure.discard(role)

    def insta360_view(self) -> dict | None:
        with self.condition:
            available = "cam1" in self.cameras and "cam1" not in self.failed_roles
        if self.model_id == "conversation":
            observer = self.observers.get("cam1")
            available = bool(observer and observer.available)
        if self.model_id not in {"molmoact2", "conversation"} or not available:
            return None
        return {**self.profile["x5_view"], "defaults": DEFAULT_VIEW.copy()}

    def set_insta360_view(self, view: dict) -> dict:
        if self.insta360_view() is None:
            raise RuntimeError("Insta360 is unused by this camera profile or is not ready.")
        view = validate_view(view)
        previous = self.profile
        self.profile = {**previous, "x5_view": view, "x5_projection": projection_filter(view)}
        try:
            result = self.preview()
            if result["insta360View"] is None:
                raise RuntimeError("Insta360 is no longer ready.")
            save_view(view)
            return result
        except Exception:
            self.profile = previous
            raise

    def scene_snapshot(self) -> dict:
        """Read fresh physical sources without policy fallback, camera or motor changes."""
        after = time.monotonic()
        wall_offset = time.time() - after
        images, unavailable = [], []
        roles = (("overhead", "cam0" if self.model_id in {"conversation", "molmoact2"} else "scene"),
                 ("wrist", "wrist"))
        for label, role in roles:
            try:
                if role in self.observers:
                    rgb, stamp = self.observers[role].snapshot(after=after, with_meta=True)
                else:
                    # Do not depend on the other policy camera or duplicate it if
                    # overhead is missing. The capture thread owns camera.read().
                    deadline = time.monotonic() + 0.8
                    with self.condition:
                        while True:
                            if role not in self.cameras or role in self.failed_roles or self.stop_event.is_set():
                                raise RuntimeError("Camera unavailable.")
                            frame = self.latest.get(role)
                            if frame and frame[1] > after and time.monotonic() - frame[1] <= 0.5:
                                rgb, stamp = frame[0].copy(), frame[1]
                                break
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError("No fresh camera image.")
                            self.condition.wait(min(remaining, 0.05))
                    config = self.profile["cameras"][role]
                    if config.get("crop"):
                        rgb = crop_4x3(rgb, config["crop"])
                images.append(encode_scene_image(rgb, label, stamp + wall_offset))
            except (RuntimeError, TimeoutError, ValueError) as exc:
                unavailable.append({"camera": label, "error": str(exc)})
        return {"images": images, "unavailable": unavailable,
                "status": "ok" if len(images) == 2 else "partial" if images else "unavailable"}

    def preview(self, *, after: float = 0.0, observer_after: float = 0.0, observer_role: str | None = None) -> dict:
        views = {} if self.model_id == "conversation" else self.read_views(after=after)
        return {"model": self.model_id, "previews": self.previews(views),
                "capturedAt": time.time(), "geometry": self.profile["geometry"],
                "cameraSources": self.camera_sources(), "insta360View": self.insta360_view(),
                "cameraBrightness": self.brightness_metadata(), "cameraExposure": self.exposure_metadata(),
                "observerPreviews": self.observer_previews(after=observer_after, role=observer_role),
                "observerStatus": self.observer_status()}

    def close(self) -> None:
        if self.face_detector is not None:
            self.face_detector.stop()
        for observer in self.observers.values():
            observer.close()
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        for thread in self.threads:
            thread.join(timeout=1)
        for camera in self.cameras.values():
            camera.release()
        for thread in self.threads:
            thread.join(timeout=1)
        self.threads.clear()
        self.cameras.clear()
        self.latest.clear()
        self.failed_roles.clear()
        self.capture_error = None


class PhysicalFrameServer:
    def __init__(self, pair: CameraPair, path: Path = SOCKET_PATH):
        self.pair = pair
        self.path = Path(path)
        self.listener: socket.socket | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.clients: set[socket.socket] = set()
        self.client_lock = threading.Lock()

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.3)
                probe.connect(str(self.path))
            except (ConnectionRefusedError, FileNotFoundError):
                self.path.unlink(missing_ok=True)
            else:
                raise RuntimeError("Another camera worker owns the physical stream.")
            finally:
                probe.close()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.path))
        os.chmod(self.path, 0o600)
        listener.listen(2)
        listener.settimeout(0.2)
        self.listener = listener
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()

    def _accept_loop(self) -> None:
        assert self.listener
        while not self.stop_event.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self.client_lock:
                self.clients.add(connection)
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(2)
            hello, _ = receive_packet(connection)
            if (hello.get("op") != "hello" or hello.get("model") != self.pair.model_id
                    or hello.get("version") != self.pair.profile["version"]):
                send_packet(connection, {"ok": False, "error": "Camera profile mismatch."})
                return
            send_packet(connection, {"ok": True, "model": self.pair.model_id,
                                     "version": self.pair.profile["version"]})
            connection.settimeout(None)
            while not self.stop_event.is_set():
                command, _ = receive_packet(connection)
                if command.get("op") != "frame":
                    send_packet(connection, {"ok": False, "error": "Unknown frame command."})
                    continue
                after = float(command.get("after", 0.0))
                timeout_s = float(command.get("timeout_s", 0.8))
                if not 0 <= after <= time.monotonic() or not 0.05 <= timeout_s <= 1.0:
                    raise ValueError("Invalid timestamp or timeout.")
                views, timestamps = self.pair.read_views(after=after, with_meta=True,
                                                         timeout_s=timeout_s)
                payload = b"".join(views[role].tobytes() for role in self.pair.profile["cameras"])
                send_packet(connection, {
                    "ok": True, "model": self.pair.model_id,
                    "version": self.pair.profile["version"],
                    "timestamp": max(timestamps.values()),
                    "camera_timestamps": timestamps,
                    "camera_sources": self.pair.camera_sources(),
                    "views": {role: {"shape": list(views[role].shape), "dtype": "uint8"}
                              for role in self.pair.profile["cameras"]},
                }, payload)
        except (ConnectionError, BrokenPipeError, OSError):
            pass
        except Exception as exc:
            try:
                send_packet(connection, {"ok": False, "error": str(exc)})
            except OSError:
                pass
        finally:
            with self.client_lock:
                self.clients.discard(connection)
            connection.close()

    def close(self) -> None:
        self.stop_event.set()
        if self.listener:
            self.listener.close()
        with self.client_lock:
            clients = list(self.clients)
        for connection in clients:
            connection.close()
        if self.thread:
            self.thread.join(timeout=1)
        self.path.unlink(missing_ok=True)


def serve(model_id: str) -> None:
    pair = CameraPair(model_id)
    server = PhysicalFrameServer(pair)
    try:
        pair.connect()
        pair.initialize_brightness()
        pair.initialize_exposure()
        if model_id != "conversation":
            server.start()
        print("RESULT_JSON:" + json.dumps({"model": model_id, "ready": True}), flush=True)
        for line in sys.stdin:
            try:
                command = json.loads(line)
                op = command.get("op")
                if op == "stop":
                    return
                if op == "insta360_view":
                    result = pair.set_insta360_view(command.get("view"))
                elif op == "brightness":
                    result = pair.set_camera_brightness(command.get("role"), command.get("value"))
                elif op == "exposure":
                    result = pair.set_camera_exposure(command.get("role"), command.get("value"))
                elif op == "face_tracking":
                    result = pair.face_tracking(command.get("action", "status"))
                elif op == "scene_snapshot":
                    result = pair.scene_snapshot()
                elif op in {"preview", "capture"}:
                    if op == "capture" and model_id == "conversation":
                        raise ValueError("Conversation cameras provide previews only.")
                    result = pair.preview() if op == "preview" else pair.capture()
                else:
                    raise ValueError("Unknown camera command.")
                print("RESULT_JSON:" + json.dumps(result), flush=True)
            except Exception as exc:
                print("ERROR_JSON:" + json.dumps({"error": str(exc)}), flush=True)
    except Exception as exc:
        # Startup failures must use the same protocol as command failures, so
        # the UI receives the cause instead of only an unexpected EOF.
        print("ERROR_JSON:" + json.dumps({"error": str(exc)}), flush=True)
        raise
    finally:
        if model_id != "conversation":
            server.close()
        pair.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model_id", choices=("molmoact2", "conversation"))
    serve(parser.parse_args().model_id)
