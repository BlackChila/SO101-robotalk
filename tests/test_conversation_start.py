"""Start-mode selection without launching processes or accessing hardware."""
import asyncio
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import asr_web


class ConversationStartTests(unittest.TestCase):
    def test_default_replays_intro_and_explicit_skip_selects_only_positioning(self):
        for options, skip in ((None, False), (asr_web.ConversationMotionStart(skipIntro=True), True),
                              (asr_web.ConversationMotionStart(realtimeIntro=True), False)):
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                (root / 'outputs').mkdir()
                for name in ('take', 'runner', 'python'):
                    (root / name).touch()
                for name, value in {'ROOT': root, 'INTRO_TAKE': root/'take',
                        'CONVERSATION_MOTION_RUNNER': root/'runner', 'FLUX_PYTHON': root/'python',
                        '_conversation_motion_process': None, '_conversation_motion_report': None,
                        '_conversation_motion_id': None, '_conversation_motion_fault': None,
                        '_conversation_motion_return_requested': False}.items():
                    stack.enter_context(patch.object(asr_web, name, value))
                stack.enter_context(patch.object(asr_web, 'follower_port_available', return_value=True))
                stack.enter_context(patch.object(asr_web, 'reset_state', return_value=('idle', None)))
                stack.enter_context(patch.object(asr_web, 'torque_state', return_value=('idle', None)))
                stack.enter_context(patch.object(asr_web.teleoperation_session, 'status', return_value={'occupied': False}))
                launch = stack.enter_context(patch.object(asr_web.subprocess, 'Popen', return_value=Mock()))
                result = asyncio.run(asr_web.conversation_motion_start(
                    SimpleNamespace(headers={'x-so101-conversation': 'operator-call'}), options))
                self.assertEqual(result['status'], 'starting')
                args = launch.call_args.args[0]
                self.assertEqual('--skip-intro' in args, skip)
                self.assertEqual('--realtime-intro' in args, bool(options and options.realtimeIntro))
                self.assertNotIn('--return-only', args)

    def test_skip_flag_is_strict_and_rejects_unknown_fields(self):
        for value in ('false', 1, None):
            with self.assertRaises(ValidationError):
                asr_web.ConversationMotionStart(skipIntro=value)
        with self.assertRaises(ValidationError):
            asr_web.ConversationMotionStart(targetPose={})
