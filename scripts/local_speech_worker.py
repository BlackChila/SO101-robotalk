"""Serialized JSON-line client for isolated local speech model processes."""

import atexit
import json
import select
import subprocess
import tempfile
import threading
from pathlib import Path


class LocalSpeechWorker:
    def __init__(self, python: Path, script: Path, name: str):
        self.python = python
        self.script = script
        self.name = name
        self.process = None
        self.log = None
        self.lock = threading.Lock()
        atexit.register(self.close)

    def close(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None
            if self.log:
                self.log.close()
                self.log = None

    def _read(self, timeout: float) -> dict:
        assert self.process and self.process.stdout
        if not select.select([self.process.stdout], [], [], timeout)[0]:
            raise TimeoutError(f"{self.name} worker timed out")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f"{self.name} worker exited; see output log")
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(response["error"])
        return response

    def _ensure_ready_locked(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        if not self.python.is_file() or not self.script.is_file():
            raise RuntimeError(f"{self.name} runtime is not installed")
        if self.log:
            self.log.close()
        log_path = Path(tempfile.gettempdir()) / f"so101-{self.name}-worker.log"
        self.log = log_path.open("a")
        self.process = subprocess.Popen(
            [str(self.python), str(self.script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, bufsize=1, cwd=self.script.parent.parent,
        )
        try:
            ready = self._read(180)
            if ready.get("ready") is not True:
                raise RuntimeError(f"{self.name} worker did not become ready")
        except Exception:
            self.process.kill()
            self.process = None
            raise

    def ensure_ready(self) -> None:
        """Load the worker without generating speech."""
        with self.lock:
            self._ensure_ready_locked()

    def request(self, payload: dict, *, timeout: float = 180) -> dict:
        with self.lock:
            self._ensure_ready_locked()
            assert self.process.stdin
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            try:
                return self._read(timeout)
            except Exception:
                self.process.kill()
                self.process = None
                raise
