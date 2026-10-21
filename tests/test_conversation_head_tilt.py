"""Offline gesture timing, bounds, and stale-camera behavior."""
import random
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from conversation_head_tilt import HeadTiltAnimator


class HeadTiltTests(unittest.TestCase):
    def test_occasional_gestures_go_both_ways_and_return_to_neutral(self):
        animator = HeadTiltAnimator(.4, (-180, 180), 0, random.Random(7))
        measured = .4
        peaks = []
        pauses = 0
        for i in range(1, 15001):
            now = i * .02
            previous, phase = measured, animator.phase
            measured = animator.goal(now, measured, True)
            self.assertLessEqual(abs(measured - previous), .24 + 1e-8)
            self.assertLessEqual(abs(measured - .4), 20 + 1e-8)
            if phase != 'hold' and animator.phase == 'hold':
                peaks.append(measured - .4)
            if animator.phase == 'pause':
                pauses += 1
                self.assertAlmostEqual(measured, .4)
            if now < .5:
                self.assertEqual(measured, .4)
        self.assertGreater(pauses, 500)
        self.assertGreater(len(peaks), 35)
        self.assertTrue(all(a * b < 0 for a, b in zip(peaks, peaks[1:])))
        self.assertTrue(any(abs(p) > 15 for p in peaks))
        self.assertTrue(any(p >= 2 for p in peaks))
        self.assertTrue(any(p <= -2 for p in peaks))

    def test_camera_loss_holds_measured_roll_and_resume_returns_smoothly(self):
        animator = HeadTiltAnimator(.4, (-180, 180), 0, random.Random(1))
        measured = .4
        for i in range(1, 601):
            measured = animator.goal(i * .02, measured, True)
        measured = 3.0
        self.assertEqual(animator.goal(12.02, measured, False), measured)
        self.assertEqual(animator.goal(100, measured, False), measured)
        resumed = animator.goal(100.02, measured, True)
        self.assertLessEqual(abs(resumed - measured), .24)
        for i in range(1, 101):
            resumed = animator.goal(100.02 + i * .02, resumed, True)
        self.assertAlmostEqual(resumed, .4)

    def test_calibration_and_measured_lead_are_respected_with_stalled_joint(self):
        animator = HeadTiltAnimator(0, (-3, 4), 0, random.Random(1))
        for i in range(1, 5001):
            goal = animator.goal(i * .02, 0, True)
            self.assertLessEqual(abs(goal), 2)
            self.assertGreaterEqual(goal, -3)
            self.assertLessEqual(goal, 4)
        self.assertEqual(animator.goal(101, 5, True), 5)
        self.assertEqual(animator.phase, 'paused')

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ValueError):
            HeadTiltAnimator(80, (-180, 180), 0)
        animator = HeadTiltAnimator(.4, (-180, 180), 0)
        with self.assertRaises(ValueError):
            animator.goal(float('nan'), .4, True)


if __name__ == '__main__':
    unittest.main()
