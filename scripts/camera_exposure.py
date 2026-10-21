"""Manual shutter controls in 100 microsecond units, persisted per device."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from camera_brightness import probe_control

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config/camera-exposure.local.json"
MAX_EXPOSURE = 333  # One 30-fps frame interval, rather than the sensor's 500-ms maximum.


def probe_exposure(device: str) -> dict | None:
    control = probe_control(device, "exposure_time_absolute")
    if control is not None:
        control["max"] = min(control["max"], MAX_EXPOSURE)
    return control


def validate_exposure(value: int, control: dict) -> int:
    if (isinstance(value, bool) or not isinstance(value, int)
            or not control["min"] <= value <= control["max"]
            or (value - control["min"]) % max(1, control["step"])):
        raise ValueError("Belichtung liegt außerhalb des Kamerabereichs für 30 Bilder/s.")
    return value


def set_exposure(device: str, value: int, control: dict) -> dict:
    validate_exposure(value, control)
    subprocess.run(["v4l2-ctl", "--device", device, "--set-ctrl",
                    f"auto_exposure=1,exposure_time_absolute={value}"],
                   capture_output=True, text=True, timeout=5, check=True)
    actual = probe_exposure(device)
    mode = subprocess.run(["v4l2-ctl", "--device", device, "--get-ctrl", "auto_exposure"],
                          capture_output=True, text=True, timeout=5, check=True)
    manual = re.fullmatch(r"auto_exposure:\s*1(?:\s*\([^\n]*\))?", mode.stdout.strip())
    if actual is None or actual["value"] != value or not manual:
        raise RuntimeError("Die Kamera hat die manuelle Belichtung nicht bestätigt.")
    return actual


def load_exposure() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    saved = json.loads(SETTINGS_PATH.read_text())
    if not isinstance(saved, dict) or any(not isinstance(k, str) or isinstance(v, bool)
                                         or not isinstance(v, int) for k, v in saved.items()):
        raise ValueError("Ungültige gespeicherte Kamerabelichtung.")
    return saved


def save_exposure(device: str, value: int) -> None:
    saved = {**load_exposure(), device: value}
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
