"""Bridge local face observations to the existing conversation motor owner.

This module never opens cameras or serial devices. Only explicit enable arms
motion; a new task, lost owner, or detector failure requires another enable.
"""
from __future__ import annotations

import threading
import uuid


class FaceTrackingSession:
    def __init__(self, camera, motion_status, send_motion, task_active):
        self.camera = camera
        self.motion_status = motion_status
        self.send_motion = send_motion
        self.task_active = task_active
        self.lock = threading.RLock()
        self.actions = threading.Lock()
        self.mode = "off"
        self.session_id = None
        self.error = None
        self.generation = 0
        self.cancel = threading.Event()
        self.thread = None

    def _ready(self, session_id):
        status = self.motion_status()
        if (not session_id or status.get("sessionId") != session_id
                or not status.get("active") or status.get("state") != "holding"
                or status.get("returnRequested")
                or self.task_active()):
            raise RuntimeError("Face-Tracking erfordert einen gehaltenen Gesprächsarm ohne Manipulationsauftrag.")
        if status.get("taskWasStarted"):
            raise RuntimeError("Nach einer Manipulation erst eine neue Gesprächssitzung in geprüfter Haltung starten.")
        return status

    def _disable_locked(self, reason=None):
        self.generation += 1
        self.cancel.set()
        session_id = self.session_id
        self.mode = "preview" if self.mode != "off" else "off"
        self.session_id = None
        self.error = reason
        if session_id:
            try:
                self.send_motion(session_id, {"op": "face_tracking", "enabled": False})
            except (RuntimeError, OSError) as exc:
                self.error = f"Tracking gestoppt; Controller-Halt prüfen: {exc}"
                raise

    def disable(self, reason=None):
        # Invalidates forwarding before writing disable, including a camera RPC
        # already in flight. No join while the camera worker might be blocked.
        with self.lock:
            self._disable_locked(reason)

    def command(self, action, session_id=None, search=True, search_direction="right", *, require_owner=False):
        if search_direction not in ("left", "right"):
            raise ValueError("Invalid initial search direction")
        with self.actions:
            # Browser requests are scoped to their call. Internal task/stop and
            # shutdown cleanup retain their authoritative, unscoped stop path.
            with self.lock:
                if require_owner and self.session_id and session_id != self.session_id:
                    raise RuntimeError("Face-Tracking gehört einer anderen Gesprächssitzung.")
            if action in {"disable", "stop"}:
                self.disable()
                if action == "stop":
                    try:
                        if self.camera.model_id in {"conversation", "molmoact2"}:
                            self.camera.face_tracking("stop")
                    finally:
                        with self.lock:
                            self.mode = "off"
                return self.status()
            if action not in {"preview", "enable"}:
                raise ValueError("Unbekannte Face-Tracking-Aktion.")
            if self.camera.model_id not in {"conversation", "molmoact2"}:
                raise RuntimeError("Zuerst die Gesprächskameras öffnen.")
            if action == "enable":
                self._ready(session_id)
            with self.lock:
                self._disable_locked()
                operation_generation = self.generation
            try:
                vision = self.camera.face_tracking("start")
                if not vision.get("running"):
                    raise RuntimeError(vision.get("error") or "Gesichtsdetektor nicht bereit.")
            except (RuntimeError, OSError, ValueError) as exc:
                with self.lock:
                    if operation_generation == self.generation:
                        self.error = str(exc)
                raise
            with self.lock:
                if operation_generation != self.generation:
                    raise RuntimeError("Face-Tracking-Start wurde durch Stop abgebrochen.")
                self.mode = "preview"
                self.error = None
                if action == "enable":
                    self._ready(session_id)
                    # Forwarding begins only after enable was sent successfully.
                    request_id = uuid.uuid4().hex
                    self.send_motion(session_id, {"op": "face_tracking", "enabled": True,
                                                  "search": bool(search), "search_direction": search_direction,
                                                  "request_id": request_id})
                    self.session_id = session_id
                    self.mode = "tracking"
                    self.cancel = threading.Event()
                    generation, cancel = self.generation, self.cancel
                    self.thread = threading.Thread(target=self._forward,
                        args=(session_id, generation, cancel, request_id), daemon=True,
                        name="conversation-face-tracking")
                    self.thread.start()
            return self.status()

    def _forward(self, session_id, generation, cancel, request_id):
        last_sequence = None
        while not cancel.is_set():
            try:
                motion = self._ready(session_id)
                control = motion.get("faceTracking", {})
                if control.get("request_id") == request_id and (control.get("error") or control.get("state") == "blocked"):
                    raise RuntimeError(control.get("error") or "Motorcontroller hat Face-Tracking abgelehnt.")
                vision = self.camera.face_tracking("status")
                if not vision.get("running") or vision.get("error"):
                    raise RuntimeError(vision.get("error") or "Gesichtsdetektor wurde beendet.")
                observation = vision.get("observation")
                if observation and observation.get("sequence") != last_sequence:
                    with self.lock:
                        if generation != self.generation or cancel.is_set():
                            return
                        self._ready(session_id)
                        self.send_motion(session_id, {"op": "face_observation",
                                                       "observation": observation})
                        last_sequence = observation.get("sequence")
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                with self.lock:
                    if generation == self.generation:
                        try:
                            self._disable_locked(str(exc))
                        except (RuntimeError, OSError):
                            pass  # Motor worker independently expires stale input.
                return
            cancel.wait(0.1)

    def status(self):
        with self.lock:
            mode, session_id, error = self.mode, self.session_id, self.error
        vision = None
        if mode != "off" and self.camera.model_id in {"conversation", "molmoact2"}:
            try:
                vision = self.camera.face_tracking("status")
            except (RuntimeError, OSError, ValueError) as exc:
                error = str(exc)
        motion = self.motion_status()
        return {"mode": mode, "sessionId": session_id, "error": error,
                "vision": vision, "control": motion.get("faceTracking", {})}
