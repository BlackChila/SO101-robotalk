"""Pure two-axis gaze control; no camera, motor, or policy ownership here.

Coordinates refer to the upright (90-degree clockwise rotated) wrist image.
Positive shoulder_pan looks right and positive wrist_flex looks down. These
signs still require a supervised check in the final software-rotated posture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

AXES = ("shoulder_pan", "wrist_flex")
TRACKING_TARGET_X = 0.90
TRACKING_TARGET_Y = 0.5


@dataclass(frozen=True)
class TrackingConfig:
    stale_s: float = 0.5
    search_delay_s: float = 1.0
    search_tilt_delay_s: float = 0.35
    search_up_angle: float = 70.0
    search_tilt_speed: float = 4.0
    gain: float = 62.4  # degrees/sec per normalized image offset
    dead_zone: float = 0.06
    filter_time_s: float = 0.12
    max_speed: float = 10.4
    acceleration: float = 26.0
    search_speed: float = 16.0
    wrist_speed_scale: float = 1.0
    max_lead: float = 2.0  # degrees ahead of actual measured joints
    base_range: float = 95.0
    wrist_up_range: float = 70.0
    wrist_down_range: float = 50.0
    confidence: float = 0.7
    target_x: float = TRACKING_TARGET_X
    target_y: float = TRACKING_TARGET_Y


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


class FaceTrackingController:
    """Generate small bounded targets from fresh observations, disabled by default."""

    def __init__(self, bounds: dict, config: TrackingConfig | None = None):
        self.config = config or TrackingConfig()
        self.bounds = {name: tuple(bounds[name]) for name in AXES}
        for low, high in self.bounds.values():
            if not all(math.isfinite(v) for v in (low, high)) or low >= high:
                raise ValueError("Invalid face-tracking calibration bounds")
        self.enabled = False
        self.state = "disabled"
        self.observation = None
        self.last_sequence = -1
        self.last_captured_at = -math.inf
        self.enabled_at = math.inf
        self.last_tick = None
        self.filtered = None
        self.no_face_since = None
        self.targets = {}
        self.velocity = {axis: 0.0 for axis in AXES}
        self.limits = {}
        self.limit_reached = {}
        self.search_direction = 1
        self.search_wrist_target = None

    def enable(self, measured: dict, now: float, *, search: bool = True, search_direction: str = "right") -> None:
        self.disable()
        self._validate_measured(measured)
        roll = measured.get("wrist_roll")
        if type(roll) not in (float, int) or not math.isfinite(roll) or abs(roll - 0.4) > 10:
            raise ValueError("Face tracking requires natural wrist roll within 10 degrees of 0.4")
        if (not math.isfinite(now) or type(search) is not bool
                or search_direction not in ("left", "right")):
            raise ValueError("Invalid tracking enable request")
        self.enabled = True
        self.search = search
        self.enabled_at = now
        self.last_tick = now
        self.targets = {axis: float(measured[axis]) for axis in AXES}
        spans = ((self.config.base_range, self.config.base_range),
                 (self.config.wrist_up_range, self.config.wrist_down_range))
        for axis, (negative_span, positive_span) in zip(AXES, spans):
            low, high = self.bounds[axis]
            if not low <= measured[axis] <= high:
                self.disable()
                raise ValueError(f"{axis} is outside calibration")
            self.limits[axis] = (max(low, measured[axis] - negative_span),
                                 min(high, measured[axis] + positive_span))
        self.search_direction = -1 if search_direction == "left" else 1
        self.state = "waiting_for_camera"

    def disable(self) -> None:
        self.search_wrist_target = None
        self.limit_reached = {}
        self.enabled = False
        self.state = "disabled"
        self.observation = None
        self.last_sequence = -1
        self.last_captured_at = -math.inf
        self.filtered = None
        self.no_face_since = None
        self.last_tick = None
        self.velocity = {axis: 0.0 for axis in AXES}

    def observe(self, observation: dict, now: float) -> bool:
        """Reject malformed, duplicate, pre-enable, future, and stale captures."""
        if not self.enabled or not isinstance(observation, dict):
            return False
        sequence = observation.get("sequence")
        captured = observation.get("captured_at")
        detected = observation.get("detected")
        if (type(sequence) is not int or sequence <= self.last_sequence
                or type(captured) not in (int, float) or not math.isfinite(captured)
                or not math.isfinite(now) or type(detected) is not bool
                or captured < self.enabled_at or captured <= self.last_captured_at
                or not 0 <= now - captured <= self.config.stale_s):
            return False
        if detected:
            values = [observation.get(key) for key in ("x", "y", "confidence")]
            if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
                   for v in values):
                return False
            if values[2] < self.config.confidence:
                detected = False
        previous_capture = self.last_captured_at
        if captured - previous_capture > self.config.stale_s:
            self.no_face_since = None
            self.search_wrist_target = None
            self.filtered = None
        self.last_sequence = sequence
        self.last_captured_at = captured
        self.observation = {**observation, "detected": detected}
        if detected:
            # The gripper occupies the left side of the upright camera image.
            # Keep the face at the configured offset toward the opposite edge,
            # while retaining the vertical target at half the image height.
            raw = (observation["x"] - self.config.target_x,
                   observation["y"] - self.config.target_y)
            if self.filtered is None:
                self.filtered = raw
            else:
                alpha = 1 - math.exp(-(captured - previous_capture) / self.config.filter_time_s)
                self.filtered = tuple(old + alpha * (new - old)
                                      for old, new in zip(self.filtered, raw))
            self.no_face_since = None
            self.search_wrist_target = None
        else:
            self.filtered = None
            if self.no_face_since is None:
                self.no_face_since = captured
        return True

    def _validate_measured(self, measured: dict) -> None:
        if any(axis not in measured or not math.isfinite(measured[axis]) for axis in AXES):
            raise ValueError("Invalid measured gaze position")

    def _hold(self, measured: dict, state: str) -> dict:
        self.state = state
        self.velocity = {axis: 0.0 for axis in AXES}
        self.targets = {axis: float(measured[axis]) for axis in AXES}
        return self.targets.copy()

    def tick(self, now: float, measured: dict) -> dict:
        self.limit_reached = {}
        if not self.enabled:
            return {}
        self._validate_measured(measured)
        if not math.isfinite(now):
            raise ValueError("Invalid tracking time")
        dt = clamp(now - self.last_tick, 0.0, 0.05) if self.last_tick is not None else 0.0
        self.last_tick = now
        if self.observation is None:
            return self._hold(measured, "waiting_for_camera")
        if not 0 <= now - self.last_captured_at <= self.config.stale_s:
            self.no_face_since = None
            self.search_wrist_target = None
            self.filtered = None
            return self._hold(measured, "camera_stale")
        if self.observation["detected"]:
            self.state = "tracking"
            speeds = [0.0 if abs(error) <= self.config.dead_zone else
                      clamp(self.config.gain * (error - math.copysign(self.config.dead_zone, error)),
                            -self.config.max_speed, self.config.max_speed)
                      for error in self.filtered]
            speeds[1] *= self.config.wrist_speed_scale
        elif (self.search and self.no_face_since is not None
              and now - self.no_face_since >= self.config.search_tilt_delay_s):
            self.state = "searching"
            low, high = self.limits["shoulder_pan"]
            target = self.targets["shoulder_pan"]
            if target >= high - 0.1:
                self.search_direction = -1
            elif target <= low + 0.1:
                self.search_direction = 1
            if self.search_wrist_target is None:
                self.search_wrist_target = max(self.limits["wrist_flex"][0],
                    measured["wrist_flex"] - self.config.search_up_angle)
            wrist_error = self.search_wrist_target - measured["wrist_flex"]
            wrist_speed = (0.0 if abs(wrist_error) <= 0.3 else
                           clamp(self.config.gain * wrist_error,
                                 -self.config.search_tilt_speed, self.config.search_tilt_speed))
            base_speed = (self.search_direction * self.config.search_speed
                          if now - self.no_face_since >= self.config.search_delay_s else 0.0)
            speeds = [base_speed, wrist_speed]
        else:
            return self._hold(measured, "face_lost")
        for axis, speed in zip(AXES, speeds):
            if speed == 0:
                # Centre reached: discard queued position lead immediately.
                self.velocity[axis] = 0.0
                self.targets[axis] = float(measured[axis])
                continue
            delta = self.config.acceleration * dt * (self.config.wrist_speed_scale if axis == "wrist_flex" else 1)
            velocity = clamp(speed, self.velocity[axis] - delta, self.velocity[axis] + delta)
            low, high = self.limits[axis]
            bounded = clamp(self.targets[axis] + velocity * dt, low, high)
            bounded = clamp(bounded, measured[axis] - self.config.max_lead,
                            measured[axis] + self.config.max_lead)
            # Reapply envelope after measured-lead limiting. If actual position
            # escaped it externally, hold instead of snapping to its boundary.
            if not low <= measured[axis] <= high:
                return self._hold(measured, "outside_envelope")
            self.targets[axis] = clamp(bounded, low, high)
            at_low = self.targets[axis] <= low and speed < 0
            at_high = self.targets[axis] >= high and speed > 0
            if at_low or at_high:
                self.limit_reached[axis] = "low" if at_low else "high"
                self.velocity[axis] = 0.0
            else:
                self.velocity[axis] = velocity
        return self.targets.copy()

    def status(self) -> dict:
        return {"enabled": self.enabled, "state": self.state,
                "last_sequence": self.last_sequence,
                "limit_reached": self.limit_reached.copy(),
                "targets": self.targets.copy() if self.enabled else {},
                "limits": self.limits.copy() if self.enabled else {}}
