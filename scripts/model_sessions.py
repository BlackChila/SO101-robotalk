"""One warm, hardware-free policy worker for the local speech interface.

Workers speak newline-delimited JSON on stdin and emit a single RESULT_JSON
record for each set_task request. Only one model can own the GPU session at a
time; switching models closes the previous worker first.
"""

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

ROOT = Path(__file__).resolve().parents[1]
WORKERS = {
    "molmoact2": ("molmoact2", "molmoact2_session.py"),
}
RESULT_PREFIX = b"RESULT_JSON:"
ERROR_PREFIX = b"ERROR_JSON:"


class ModelSession:
    """Serialize requests to one persistent worker without opening hardware."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model_id: str | None = None
        self._ready = False
        self._process: subprocess.Popen | None = None
        self._stdout = bytearray()
        self._log = None

    @property
    def model_id(self) -> str | None:
        with self._lock:
            return self._model_id if self._process and self._process.poll() is None else None

    @property
    def ready_model_id(self) -> str | None:
        with self._lock:
            return self.model_id if self._ready else None

    def _environment(self, model_id: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        return env

    def _start(self, model_id: str) -> None:
        env_name, script_name = WORKERS[model_id]
        python = ROOT / "environments" / env_name / ".venv/bin/python"
        script = ROOT / "scripts" / script_name
        if not python.is_file() or not script.is_file():
            raise RuntimeError(f"{model_id}: session worker or Python environment is missing.")
        log_dir = ROOT / "outputs/model-sessions"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log = (log_dir / f"{model_id}.log").open("ab")
        try:
            self._process = subprocess.Popen(
                [str(python), "-u", str(script)], cwd=ROOT,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                env=self._environment(model_id), start_new_session=True,
            )
        except BaseException:
            self._log.close()
            self._log = None
            raise
        self._model_id = model_id
        self._ready = False
        self._stdout.clear()

    def preload(self, model_id: str, timeout_s: float = 420) -> dict:
        """Load checkpoint weights now, without generating an action or opening hardware."""
        if model_id not in WORKERS:
            raise ValueError("Unknown model.")
        with self._lock:
            if model_id != self.model_id:
                self._stop_locked()
                self._start(model_id)
            if self._ready:
                return {"model": model_id, "ready": True, "hardwareCommands": False}
            assert self._process and self._process.stdin
            try:
                self._process.stdin.write(b'{"op":"warm"}\n')
                self._process.stdin.flush()
                result = self._next_record(timeout_s)
                if (result.get("model") != model_id or result.get("ready") is not True
                        or result.get("hardwareCommands") is not False):
                    raise RuntimeError(result.get("error") or "The model was not loaded.")
                self._ready = True
                return result
            except BaseException:
                self._stop_locked()
                raise

    def _next_record(self, timeout_s: float) -> dict:
        assert self._process and self._process.stdout
        deadline = time.monotonic() + timeout_s
        while True:
            while b"\n" in self._stdout:
                line, _, rest = self._stdout.partition(b"\n")
                self._stdout = bytearray(rest)
                if line.startswith(RESULT_PREFIX):
                    try:
                        result = json.loads(line[len(RESULT_PREFIX):])
                    except (UnicodeError, ValueError) as exc:
                        raise RuntimeError("The model worker returned invalid JSON.") from exc
                    if not isinstance(result, dict):
                        raise RuntimeError("The model worker returned no result report.")
                    return result
                if line.startswith(ERROR_PREFIX):
                    try:
                        failure = json.loads(line[len(ERROR_PREFIX):])
                    except (UnicodeError, ValueError) as exc:
                        raise RuntimeError("The model worker returned an invalid error message.") from exc
                    detail = failure.get("error") if isinstance(failure, dict) else None
                    raise RuntimeError(str(detail or "The model worker reported an error."))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("The model run timed out.")
            readable, _, _ = select.select([self._process.stdout], [], [], min(remaining, 1.0))
            if readable:
                data = os.read(self._process.stdout.fileno(), 65536)
                if not data:
                    raise RuntimeError(f"The model worker exited before returning a result (exit={self._process.poll()}).")
                self._stdout.extend(data)
                if len(self._stdout) > 4 * 1024 * 1024:
                    raise RuntimeError("The model worker returned too much output data.")
            elif self._process.poll() is not None:
                raise RuntimeError(f"The model worker exited before returning a result (exit={self._process.returncode}).")

    def set_task(self, model_id: str, task: str, *, camera_npz: str | None = None,
                 timeout_s: float = 420) -> dict:
        if model_id not in WORKERS:
            raise ValueError("Unknown model.")
        task = task.strip()
        if not task or len(task) > 500:
            raise ValueError("The instruction must contain 1 to 500 characters.")
        with self._lock:
            if model_id != self.model_id:
                self._stop_locked()
                self._start(model_id)
            assert self._process and self._process.stdin
            try:
                command = {"op": "set_task", "task": task}
                if camera_npz is not None:
                    command["camera_npz"] = camera_npz
                self._process.stdin.write((json.dumps(command, ensure_ascii=False) + "\n").encode())
                self._process.stdin.flush()
                result = self._next_record(timeout_s)
            except BaseException:
                self._stop_locked()
                raise
            if result.get("error"):
                raise RuntimeError(str(result["error"]))
            self._ready = True
            return result

    def predict_chunk(self, model_id: str, task: str, *, observation_npz: str,
                      state: dict, timeout_s: float = 420) -> dict:
        """Predict from live holder data without opening hardware or preloading a new model."""
        if model_id not in WORKERS or model_id != self.ready_model_id:
            raise RuntimeError("The selected model must be loaded before motor execution.")
        task = task.strip()
        if not task or len(task) > 500:
            raise ValueError("The instruction must contain 1 to 500 characters.")
        with self._lock:
            assert self._process and self._process.stdin
            command = {"op": "predict_chunk", "task": task,
                       "state": state, "observation_npz": observation_npz,
                       "camera_npz": observation_npz}
            try:
                self._process.stdin.write((json.dumps(command, ensure_ascii=False) + "\n").encode())
                self._process.stdin.flush()
                result = self._next_record(timeout_s)
            except BaseException:
                self._stop_locked()
                raise
            if result.get("error"):
                raise RuntimeError(str(result["error"]))
            return result

    def _stop_locked(self) -> None:
        process = self._process
        if process is not None:
            if process.poll() is None and process.stdin:
                try:
                    process.stdin.write(b'{"op":"stop"}\n')
                    process.stdin.flush()
                    process.wait(timeout=3)
                except (OSError, BrokenPipeError, subprocess.TimeoutExpired):
                    pass
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired as exc:
                        # Keep the reference so another model cannot start
                        # while this process might still hold GPU allocations.
                        raise RuntimeError("The previous model process could not be stopped.") from exc
            if process.poll() is None:
                raise RuntimeError("The previous model process is still running.")
            # A worker crash must not leave descendants holding GPU memory.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("The previous model process or a child process is still running.")
            if process.stdin:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    # A cancelled worker may exit before buffered input flushes.
                    pass
            if process.stdout:
                process.stdout.close()
        self._process = None
        self._model_id = None
        self._ready = False
        self._stdout.clear()
        if self._log:
            self._log.close()
            self._log = None

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def interrupt_active_request(self) -> None:
        """Abort a slow prediction after the physical task has been stopped.

        The prediction thread owns ``_lock`` while waiting for its worker. The
        worker runs in a separate process group and has no motor connection;
        terminating it makes that thread unwind and release the task lock.
        """
        process = self._process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


session = ModelSession()
atexit.register(session.stop)
