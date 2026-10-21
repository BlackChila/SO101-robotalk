"""Hardware-free checks for UI-owned teleoperation lifecycle."""

import sys
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from teleoperation_session import TeleoperationSession  # noqa: E402


class TeleoperationSessionTests(unittest.TestCase):
    def test_active_limit_message_is_forwarded_and_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = TeleoperationSession(Path(sys.executable), root / "runner.py", root)
            session._process = MagicMock()
            session._process.poll.return_value = None
            session._report = root / "report.json"
            for message in ("Teleoperation is running · joint limit reached: wrist_flex",
                            "Teleoperation is running. The Follower follows the Leader."):
                session._report.write_text(json.dumps({"state": "active", "message": message}))
                self.assertEqual(session.status()["message"], message)
            session._state = "stopping"
            session._message = "Checking hold state."
            self.assertEqual(session.status()["message"], "Checking hold state.")

    def test_start_stop_waits_for_verified_hold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = root / "fake_runner.py"
            runner.write_text(textwrap.dedent("""
                import json
                import sys
                from pathlib import Path
                report = Path(sys.argv[sys.argv.index('--report') + 1])
                report.write_text(json.dumps({'state': 'active', 'hold_verified': None}))
                for line in sys.stdin:
                    if line.strip() == 'q':
                        report.write_text(json.dumps({'state': 'stopped', 'hold_verified': True}))
                        break
            """))
            session = TeleoperationSession(Path(sys.executable), runner, root)
            try:
                self.assertEqual(session.start()["state"], "active")
                self.assertTrue(session.status()["occupied"])
                with self.assertRaisesRegex(RuntimeError, "already"):
                    session.start()
                stopped = session.stop()
                self.assertEqual(stopped["state"], "stopped")
                self.assertTrue(stopped["holdVerified"])
                self.assertFalse(stopped["occupied"])
            finally:
                if session.status()["occupied"]:
                    session.stop()

    def test_start_surfaces_runner_failure_without_claiming_hold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = root / "fake_runner.py"
            runner.write_text(textwrap.dedent("""
                import json
                import sys
                from pathlib import Path
                report = Path(sys.argv[sys.argv.index('--report') + 1])
                report.write_text(json.dumps({'state': 'failed', 'hold_verified': False,
                                              'error': 'Follower hold unverified'}))
            """))
            session = TeleoperationSession(Path(sys.executable), runner, root)
            with self.assertRaisesRegex(RuntimeError, "Follower hold unverified"):
                session.start()
            state = session.status()
            self.assertEqual(state["state"], "failed")
            self.assertFalse(state["holdVerified"])


if __name__ == "__main__":
    unittest.main()
