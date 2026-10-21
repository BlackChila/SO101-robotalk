"""Persist the X5 viewing direction and bounded 4:3 digital zoom."""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config/insta360-view.local.json"
DEFAULT_VIEW = {"yaw": 65.0, "pitch": 15.0, "roll": 55.0, "zoom": 1.0}
VIEW_LIMITS = {"yaw": (-180, 180), "pitch": (-90, 90), "roll": (-180, 180)}
ZOOM_LIMITS = (1.0, 2.0)


def validate_view(view: dict) -> dict:
    if not isinstance(view, dict) or set(view) not in (set(VIEW_LIMITS), set(DEFAULT_VIEW)):
        raise ValueError("Insta360 requires yaw, pitch, roll and optional zoom.")
    result = {}
    for key, (low, high) in VIEW_LIMITS.items():
        value = view[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not low <= value <= high):
            raise ValueError(f"Insta360 {key} must be between {low}° and {high}°.")
        result[key] = float(value)
    zoom = view.get("zoom", 1.0)
    if (isinstance(zoom, bool) or not isinstance(zoom, (int, float))
            or not math.isfinite(zoom) or not ZOOM_LIMITS[0] <= zoom <= ZOOM_LIMITS[1]):
        raise ValueError("Insta360 zoom must be between 1 and 2.")
    result["zoom"] = float(zoom)
    return result


def load_view() -> dict:
    if not SETTINGS_PATH.exists():
        return DEFAULT_VIEW.copy()
    return validate_view(json.loads(SETTINGS_PATH.read_text()))


def save_view(view: dict) -> None:
    view = validate_view(view)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=SETTINGS_PATH.parent,
                                         delete=False) as output:
            temporary = Path(output.name)
            json.dump(view, output)
            output.write("\n")
        os.replace(temporary, SETTINGS_PATH)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def projection_filter(view: dict) -> str:
    view = validate_view(view)
    h_fov, v_fov = 52 / view["zoom"], 39 / view["zoom"]
    return ("v360=input=e:output=flat:"
            f"yaw={view['yaw']:g}:pitch={view['pitch']:g}:roll={view['roll']:g}:"
            f"h_fov={h_fov:g}:v_fov={v_fov:g}:w=960:h=720")
