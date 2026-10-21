"""Native V4L2 brightness controls, persisted by physical device identity."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config/camera-brightness.local.json"


def probe_control(device: str, name: str) -> dict | None:
    result = subprocess.run(["v4l2-ctl", "--device", device, "--list-ctrls"],
                            capture_output=True, text=True, timeout=5, check=True)
    for line in result.stdout.splitlines():
        if re.match(rf"\s*{re.escape(name)}\s", line):
            if "inactive" in line or "disabled" in line or "read-only" in line:
                return None
            values = {key: int(value) for key, value in
                      re.findall(r"\b(min|max|step|default|value)=(-?\d+)", line)}
            if set(values) == {"min", "max", "step", "default", "value"}:
                return values
    return None


def probe_brightness(device: str) -> dict | None:
    return probe_control(device, "brightness")


def validate_brightness(value: int, control: dict) -> int:
    if (isinstance(value, bool) or not isinstance(value, int)
            or not control["min"] <= value <= control["max"]
            or (value - control["min"]) % max(1, control["step"])):
        raise ValueError("Brightness is outside the camera range.")
    return value


def set_brightness(device: str, value: int, control: dict) -> dict:
    validate_brightness(value, control)
    subprocess.run(["v4l2-ctl", "--device", device, "--set-ctrl", f"brightness={value}"],
                   capture_output=True, text=True, timeout=5, check=True)
    actual = probe_brightness(device)
    if actual is None or actual["value"] != value:
        raise RuntimeError("The camera did not confirm brightness.")
    return actual


def load_brightness() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    saved = json.loads(SETTINGS_PATH.read_text())
    if not isinstance(saved, dict) or any(not isinstance(k, str) or isinstance(v, bool)
                                         or not isinstance(v, int) for k, v in saved.items()):
        raise ValueError("Invalid saved camera brightness.")
    return saved


def save_brightness(device: str, value: int) -> None:
    saved = {**load_brightness(), device: value}
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=SETTINGS_PATH.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(saved, output)
            output.write("\n")
        os.replace(temporary, SETTINGS_PATH)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
