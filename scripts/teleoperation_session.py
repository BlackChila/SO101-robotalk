"""Own one UI-started Leader/Follower teleoperation process."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path


class TeleoperationSession:
    def __init__(self, python: Path, runner: Path, root: Path):
        self.python = python
        self.runner = runner
        self.root = root
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._report: Path | None = None
        self._state = "idle"
        self._message = "Teleoperation bereit."
        self._hold_verified: bool | None = None

    def status(self) -> dict:
        with self._lock:
            report = {}
            if self._report and self._report.is_file():
                try:
                    report = json.loads(self._report.read_text())
                except (OSError, ValueError):
                    pass
            process = self._process
            occupied = process is not None and process.poll() is None
            if report.get("state") == "active" and occupied and self._state != "stopping":
                self._state = "active"
                self._message = report.get("message") or "Teleoperation läuft. Follower folgt dem Leader."
            elif not occupied and process is not None:
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
                if report.get("state") == "stopped" and report.get("hold_verified") is True:
                    self._state = "stopped"
                    self._message = "Teleoperation beendet; Follower-Halt bestätigt."
                else:
                    self._state = "failed"
                    self._message = report.get("error") or "Teleoperation endete ohne bestätigten Halt."
            if report.get("hold_verified") is not None:
                self._hold_verified = report["hold_verified"]
            return {"state": self._state, "occupied": occupied,
                    "holdVerified": self._hold_verified, "message": self._message}

    def start(self) -> dict:
        with self._lock:
            if self.status()["occupied"] or self._state == "starting":
                raise RuntimeError("Teleoperation läuft oder startet bereits.")
            if not self.python.is_file() or not self.runner.is_file():
                raise RuntimeError("Teleoperations-Controller ist nicht installiert.")
            report = self.root / "outputs" / f"ui-teleop-{uuid.uuid4().hex}.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            self._state = "starting"
            self._message = "Teleoperation startet; Startpose wird geprüft."
            self._hold_verified = None
            self._report = report
            try:
                with report.with_suffix(".log").open("w") as log:
                    self._process = subprocess.Popen(
                        [str(self.python), "-u", str(self.runner), "--report", str(report)],
                        cwd=self.root, stdin=subprocess.PIPE, stdout=log,
                        stderr=subprocess.STDOUT, start_new_session=True,
                    )
            except BaseException:
                self._state = "failed"
                raise
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = self.status()
            if current["state"] == "active":
                return current
            if current["state"] in {"failed", "stopped"}:
                raise RuntimeError(current["message"])
            time.sleep(0.1)
        try:
            self.stop()
        except RuntimeError as exc:
            raise RuntimeError(f"Teleoperation wurde nicht startbereit; Stopp unbestätigt: {exc}") from exc
        raise RuntimeError("Teleoperation wurde nicht innerhalb von 30 Sekunden startbereit.")

    def stop(self) -> dict:
        with self._lock:
            current = self.status()
            if not current["occupied"] or self._process is None:
                raise RuntimeError("Keine UI-Teleoperation läuft.")
            process = self._process
            was_active = self._state == "active"
            self._state = "stopping"
            self._message = "Teleoperation stoppt; gemessener Follower-Halt wird geprüft."
        if was_active and process.stdin is not None:
            try:
                os.write(process.stdin.fileno(), b"q\n")
            except (OSError, BrokenPipeError):
                process.terminate()
        else:
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Teleoperation reagiert nicht; Follower-Halt ist unbestätigt.") from exc
        current = self.status()
        if current["state"] != "stopped" or current["holdVerified"] is not True:
            raise RuntimeError(current["message"])
        return current
