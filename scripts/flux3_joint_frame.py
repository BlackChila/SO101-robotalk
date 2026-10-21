"""Candidate LeRobot pre-#777 SO-100/101 frame bridge for shadow diagnostics.

This module does not validate that a particular checkpoint uses this frame. It
only implements the published old/new joint conversion without touching robot
calibration or motor limits.
"""

from __future__ import annotations


NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def current_to_legacy(position: dict[str, float]) -> dict[str, float]:
    """Convert current midpoint-zero degrees to LeRobot's pre-#777 degrees."""
    if set(position) != set(NAMES):
        raise ValueError("Expected the six SO-101 joints in NAMES")
    result = dict(position)
    result["shoulder_lift"] = 90.0 - position["shoulder_lift"]
    result["elbow_flex"] = 90.0 + position["elbow_flex"]
    return result


def legacy_to_current(position: dict[str, float]) -> dict[str, float]:
    """Convert postprocessed legacy absolute commands to current degrees."""
    if set(position) != set(NAMES):
        raise ValueError("Expected the six SO-101 joints in NAMES")
    result = dict(position)
    result["shoulder_lift"] = 90.0 - position["shoulder_lift"]
    result["elbow_flex"] = position["elbow_flex"] - 90.0
    return result


def floor_gripper_at_zero(action: dict[str, float]) -> dict[str, float]:
    """Apply the explicitly requested FLUX-only lower gripper limit."""
    if set(action) != set(NAMES):
        raise ValueError("Expected the six SO-101 joints in NAMES")
    result = dict(action)
    result["gripper"] = max(0.0, result["gripper"])
    return result
