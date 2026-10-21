"""Occasional bounded wrist-roll gestures, composed by the conversation owner."""
import math
import random


class HeadTiltAnimator:
    SPEED = 12.0  # degrees/s; smooth motion, separate from gaze speed
    LEAD = 2.0

    def __init__(self, neutral, bounds, now, rng=None):
        low, high = bounds
        if not all(math.isfinite(v) for v in (neutral, low, high, now)) or not low <= neutral <= high:
            raise ValueError("Invalid head-tilt pose or calibration")
        self.neutral = neutral
        # Start in the normal talking pose; gestures stay within 20 degrees of it.
        self.low, self.high = max(low, neutral - 20), min(high, neutral + 20)
        if abs(neutral - .4) > 10 or not self.low <= neutral <= self.high:
            raise ValueError("Head tilt requires a natural wrist-roll pose")
        self.rng = rng or random.Random()
        self.current = neutral
        self.last_tick = now
        self.phase = 'pause'
        self.deadline = now + self.rng.uniform(.5, 1.5)
        self.next_direction = None
        self.elapsed = 0.0

    def _move(self, target, phase):
        self.start, self.target = self.current, target
        self.duration = max(.75, abs(target - self.current) * 1.875 / self.SPEED)
        self.elapsed = 0.0
        self.phase = phase

    def goal(self, now, measured, active):
        if not all(math.isfinite(v) for v in (now, measured)):
            raise ValueError("Invalid head-tilt feedback")
        dt = max(0, min(now - self.last_tick, .05))
        self.last_tick = now
        if not active or not self.low <= measured <= self.high:
            # Camera loss or a gaze hold must also hold roll, never finish a gesture blindly.
            self.current = measured
            self.phase = 'paused'
            return measured
        if self.phase == 'paused':
            self._move(self.neutral, 'return')
        if self.phase == 'pause' and now >= self.deadline:
            choices = [(sign, min(20, room)) for sign, room in
                       ((-1, self.neutral - self.low), (1, self.high - self.neutral))
                       if room >= 2 and (self.next_direction is None or sign == self.next_direction)]
            if choices:
                sign, amplitude = self.rng.choice(choices)
                self.next_direction = -sign
                self._move(self.neutral + sign * self.rng.uniform(min(8, amplitude), amplitude), 'tilt')
            else:
                self.deadline = now + self.rng.uniform(.5, 1.5)
        if self.phase == 'hold' and now >= self.deadline:
            self._move(self.neutral, 'return')
        if self.phase in ('tilt', 'return'):
            self.elapsed = min(self.duration, self.elapsed + dt)
            t = self.elapsed / self.duration
            smooth = t * t * t * (10 - 15 * t + 6 * t * t)
            desired = self.start + (self.target - self.start) * smooth
            desired = max(self.current - self.SPEED * dt, min(self.current + self.SPEED * dt, desired))
            self.current = max(self.low, measured - self.LEAD,
                               min(self.high, measured + self.LEAD, desired))
            if self.elapsed >= self.duration and abs(measured - self.target) < .2:
                if self.phase == 'tilt':
                    self.phase = 'hold'
                    self.deadline = now + self.rng.uniform(.3, .8)
                else:
                    self.phase = 'pause'
                    self.deadline = now + self.rng.uniform(.5, 1.5)
        return self.current
