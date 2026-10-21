"""A model switch must reap the old process before loading another model."""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_sessions  # noqa: E402


WORKER = '''import json, os, sys
from pathlib import Path
name = Path(__file__).stem
events = Path(os.environ["SO101_TEST_EVENTS"])
with events.open("a") as out:
    out.write(f"start {name} {os.getpid()}\\n")
    out.flush()
sequence = 0
for line in sys.stdin:
    command = json.loads(line)
    if command["op"] == "stop":
        with events.open("a") as out:
            out.write(f"stop {name} {os.getpid()}\\n")
        break
    if command["op"] == "warm":
        with events.open("a") as out:
            out.write(f"warm {name} {os.getpid()}\\n")
        print("RESULT_JSON:" + json.dumps({"model": name, "ready": True,
            "hardwareCommands": False}), flush=True)
        continue
    sequence += 1
    print("RESULT_JSON:" + json.dumps({"model": name, "sequence": sequence}), flush=True)
'''


class ModelSessionTests(unittest.TestCase):
    def test_interrupt_active_prediction_reaps_hardware_free_worker(self) -> None:
        worker = '''import json, os, sys, time
from pathlib import Path
for line in sys.stdin:
    command = json.loads(line)
    if command["op"] == "warm":
        print('RESULT_JSON:{"model":"fake","ready":true,"hardwareCommands":false}', flush=True)
    elif command["op"] == "predict_chunk":
        Path(os.environ["SO101_TEST_EVENTS"]).write_text("predicting")
        time.sleep(60)
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events = root / "events"
            python = root / "environments/fake/.venv/bin/python"
            python.parent.mkdir(parents=True)
            python.symlink_to(sys.executable)
            script = root / "scripts/fake.py"
            script.parent.mkdir()
            script.write_text(worker)
            subject = model_sessions.ModelSession()
            failures = []
            with (patch.object(model_sessions, "ROOT", root),
                  patch.dict(model_sessions.WORKERS, {"fake": ("fake", "fake.py")}, clear=True),
                  patch.dict(os.environ, {"SO101_TEST_EVENTS": str(events)})):
                try:
                    subject.preload("fake")
                    def predict():
                        try:
                            subject.predict_chunk("fake", "move", observation_npz="/tmp/unused",
                                                  state={}, timeout_s=10)
                        except (RuntimeError, OSError):
                            failures.append(True)
                    thread = threading.Thread(target=predict)
                    thread.start()
                    deadline = time.monotonic() + 3
                    while not events.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(events.exists())
                    subject.interrupt_active_request()
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(failures, [True])
                    self.assertIsNone(subject.model_id)
                finally:
                    subject.stop()

    def test_preload_switches_processes_before_any_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events = root / "events.log"
            for name in ("a", "b"):
                python = root / "environments" / name / ".venv/bin/python"
                python.parent.mkdir(parents=True)
                python.symlink_to(sys.executable)
                script = root / "scripts" / f"{name}.py"
                script.parent.mkdir(exist_ok=True)
                script.write_text(WORKER)
            subject = model_sessions.ModelSession()
            try:
                with (
                    patch.object(model_sessions, "ROOT", root),
                    patch.dict(model_sessions.WORKERS, {"a": ("a", "a.py"),
                                                        "b": ("b", "b.py")}, clear=True),
                    patch.dict(os.environ, {"SO101_TEST_EVENTS": str(events)}),
                ):
                    self.assertTrue(subject.preload("a")["ready"])
                    first_pid = subject._process.pid
                    self.assertEqual(subject.ready_model_id, "a")
                    self.assertTrue(subject.preload("b")["ready"])
                    self.assertEqual(subject.ready_model_id, "b")
                    with self.assertRaises(ProcessLookupError):
                        os.kill(first_pid, 0)
                    self.assertEqual(subject.set_task("b", "first prompt")["sequence"], 1)
                    subject.stop()
            finally:
                subject.stop()
            labels = [" ".join(line.split()[:2]) for line in events.read_text().splitlines()]
            self.assertEqual(labels, ["start a", "warm a", "stop a", "start b", "warm b", "stop b"])

    def test_switch_reaps_previous_process_and_discards_its_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events = root / "events.log"
            for name in ("a", "b"):
                python = root / "environments" / name / ".venv/bin/python"
                python.parent.mkdir(parents=True)
                python.symlink_to(sys.executable)
                script = root / "scripts" / f"{name}.py"
                script.parent.mkdir(exist_ok=True)
                script.write_text(WORKER)
            subject = model_sessions.ModelSession()
            try:
                with (
                    patch.object(model_sessions, "ROOT", root),
                    patch.dict(model_sessions.WORKERS, {"a": ("a", "a.py"),
                                                        "b": ("b", "b.py")}, clear=True),
                    patch.dict(os.environ, {"SO101_TEST_EVENTS": str(events)}),
                ):
                    self.assertEqual(subject.set_task("a", "first")["sequence"], 1)
                    self.assertEqual(subject.set_task("a", "second")["sequence"], 2)
                    first_pid = subject._process.pid
                    self.assertEqual(subject.set_task("b", "third")["sequence"], 1)
                    self.assertEqual(subject.model_id, "b")
                    with self.assertRaises(ProcessLookupError):
                        os.kill(first_pid, 0)
                    subject.stop()
                    self.assertIsNone(subject.model_id)
            finally:
                subject.stop()
            labels = [" ".join(line.split()[:2]) for line in events.read_text().splitlines()]
            self.assertEqual(labels, ["start a", "stop a", "start b", "stop b"])


if __name__ == "__main__":
    unittest.main()
