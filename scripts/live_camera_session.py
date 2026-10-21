"""Own exactly one camera-only process for the selected UI model."""

from __future__ import annotations

import atexit
import json
import os
import select
import signal
import subprocess
import threading
import time
from pathlib import Path

from model_sessions import ROOT
from shared_camera_stream import camera_switch_guard

CAMERA_PYTHON = ROOT / "environments/robot/.venv/bin/python"
CAMERA_WORKER = ROOT / "scripts/camera_capture_worker.py"
MODEL_IDS = {"molmoact2", "conversation"}


class LiveCameraSession:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._model_id: str | None = None
        self._buffer = bytearray()
        self._snapshot: Path | None = None
        self._log = None

    @property
    def model_id(self) -> str | None:
        with self._lock:
            return self._model_id if self._process and self._process.poll() is None else None

    def _next_record(self, timeout_s: float) -> dict:
        assert self._process and self._process.stdout
        deadline = time.monotonic() + timeout_s
        while True:
            while b"\n" in self._buffer:
                line, _, rest = self._buffer.partition(b"\n")
                self._buffer = bytearray(rest)
                if line.startswith((b"RESULT_JSON:", b"ERROR_JSON:")):
                    failed = line.startswith(b"ERROR_JSON:")
                    payload = json.loads(line.split(b":", 1)[1])
                    if failed:
                        raise RuntimeError(payload.get("error", "Kamera-Worker fehlgeschlagen."))
                    return payload
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Kameraantwort hat das Zeitlimit überschritten.")
            readable, _, _ = select.select([self._process.stdout], [], [], min(remaining, 1))
            if readable:
                data = os.read(self._process.stdout.fileno(), 65536)
                if not data:
                    raise RuntimeError("Kamera-Worker wurde beendet.")
                self._buffer.extend(data)
                if len(self._buffer) > 8 * 1024 * 1024:
                    raise RuntimeError("Kameraantwort ist zu groß.")
            elif self._process.poll() is not None:
                raise RuntimeError("Kamera-Worker wurde beendet.")

    def _call(self, operation: str, timeout_s: float = 15, **payload) -> dict:
        assert self._process and self._process.stdin
        self._process.stdin.write((json.dumps({**payload, "op": operation}) + "\n").encode())
        self._process.stdin.flush()
        return self._next_record(timeout_s)

    def select(self, model_id: str) -> dict:
        if model_id not in MODEL_IDS:
            raise ValueError("Unbekanntes Kameraprofil.")
        with self._lock:
            if self.model_id == model_id:
                try:
                    return self._call("preview")
                except (RuntimeError, TimeoutError, OSError):
                    pass
            with camera_switch_guard():
                self._stop_locked()
                return self._start_locked(model_id)

    def restart(self, model_id: str) -> dict:
        if model_id not in MODEL_IDS:
            raise ValueError("Unbekanntes Kameraprofil.")
        with self._lock:
            with camera_switch_guard():
                self._stop_locked()
                return self._start_locked(model_id)

    def _start_locked(self, model_id: str) -> dict:
        if not CAMERA_PYTHON.is_file():
            raise RuntimeError("Kamera-Python-Umgebung fehlt.")
        log_dir = ROOT / "outputs/model-sessions"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log = (log_dir / "cameras.log").open("ab")
        try:
            self._process = subprocess.Popen(
                [str(CAMERA_PYTHON), "-u", str(CAMERA_WORKER), model_id],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._log, start_new_session=True,
            )
            self._model_id = model_id
            self._buffer.clear()
            ready = self._next_record(30)
            if ready.get("model") != model_id or ready.get("ready") is not True:
                raise RuntimeError("Falsches Kameraprofil aktiviert.")
            return self._call("preview")
        except BaseException:
            self._stop_locked()
            raise

    def preview(self, model_id: str) -> dict:
        with self._lock:
            if self.model_id != model_id:
                raise RuntimeError("Das ausgewählte Kameraprofil ist nicht aktiv.")
            return self._call("preview")

    def scene_snapshot(self) -> dict:
        with self._lock:
            if self.model_id is None:
                raise RuntimeError("Die Kameras sind nicht aktiv.")
            return self._call("scene_snapshot")

    def capture(self, model_id: str) -> dict:
        with self._lock:
            if self.model_id != model_id:
                raise RuntimeError("Live-Kameras für dieses Modell sind nicht aktiv.")
            result = self._call("capture", timeout_s=30)
            path = Path(result["path"])
            if result.get("model") != model_id or path.parent != ROOT / "outputs/ui-camera-inputs":
                raise RuntimeError("Kamera-Worker lieferte einen ungültigen Schnappschuss.")
            if self._snapshot:
                self._snapshot.unlink(missing_ok=True)
            self._snapshot = path
            return result

    def set_insta360_view(self, model_id: str, view: dict) -> dict:
        from insta360_view import validate_view
        view = validate_view(view)
        with self._lock:
            with camera_switch_guard():
                if model_id not in {"molmoact2", "conversation"} or self.model_id != model_id:
                    raise RuntimeError("Das Insta360-Kameraprofil ist nicht aktiv.")
                return self._call("insta360_view", view=view)

    def face_tracking(self, action: str = "status") -> dict:
        if action not in {"start", "stop", "status"}:
            raise ValueError("Unknown face tracking action.")
        with self._lock:
            if self.model_id not in {"conversation", "molmoact2"}:
                raise RuntimeError("Face tracking requires active conversation cameras.")
            return self._call("face_tracking", action=action, timeout_s=5)

    def set_camera_brightness(self, model_id: str, role: str, value: int) -> dict:
        with self._lock:
            with camera_switch_guard():
                if self.model_id != model_id:
                    raise RuntimeError("Das Kameraprofil ist nicht aktiv.")
                return self._call("brightness", role=role, value=value)

    def set_camera_exposure(self, model_id: str, role: str, value: int) -> dict:
        with self._lock:
            with camera_switch_guard():
                if self.model_id != model_id:
                    raise RuntimeError("Das Kameraprofil ist nicht aktiv.")
                return self._call("exposure", role=role, value=value)

    def _stop_locked(self) -> None:
        process = self._process
        if process:
            if process.poll() is None and process.stdin:
                try:
                    process.stdin.write(b'{"op":"stop"}\n')
                    process.stdin.flush()
                    process.wait(timeout=3)
                except (OSError, BrokenPipeError, subprocess.TimeoutExpired):
                    pass
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
        self._process = None
        self._model_id = None
        self._buffer.clear()
        if self._snapshot:
            self._snapshot.unlink(missing_ok=True)
            self._snapshot = None
        if self._log:
            self._log.close()
            self._log = None

    def stop(self) -> None:
        with self._lock:
            with camera_switch_guard():
                self._stop_locked()


camera_session = LiveCameraSession()
atexit.register(camera_session.stop)
