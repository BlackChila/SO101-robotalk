"""Camera geometry for conversation previews and the MolmoAct2 runtime.

The 4:3 crop is a local scene choice, not an upstream training-camera claim.
Policy input is cropped before the MolmoAct2 processor performs its resize.
"""
from __future__ import annotations

from copy import deepcopy
from insta360_view import load_view, projection_filter

CAPTURE_CAMERAS = {
    "scene": {
        "path": "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0",
        "width": 1280, "height": 720, "crop": [160, 0, 960, 720],
        "controls": {"auto_exposure": 1, "exposure_time_absolute": 80, "gain": 0,
                     "gamma": 100, "backlight_compensation": 0, "power_line_frequency": 1},
    },
    "wrist": {
        "path": "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-1080p-S1_SN0001-video-index0",
        "width": 1920, "height": 1080, "crop": [240, 0, 1440, 1080],
        "controls": {"auto_exposure": 1, "exposure_time_absolute": 50, "gain": 0,
                     "gamma": 100, "backlight_compensation": 0, "power_line_frequency": 1},
    },
}
X5_CAMERA = {
    "path": "/dev/v4l/by-id/usb-Insta_Insta360_X5_0001-video-index0",
    "width": 2880, "height": 1440, "crop": None,
}
MOLMO_OVERHEAD_CONTROLS = {
    "auto_exposure": 1,
    "exposure_time_absolute": 150,
    "gain": 10,
    "gamma": 100,
    "backlight_compensation": 30,
    "power_line_frequency": 1,
}


def camera_profile(model_id: str, geometry: str | None = None) -> dict:
    if model_id == "conversation":
        if geometry is not None:
            raise ValueError("Conversation preview uses fixed camera geometry")
        x5_view = load_view()
        return {
            "model": model_id, "version": "conversation-preview-v3",
            "geometry": "independent_4x3", "cameras": {}, "slots": {},
            "observer_cameras": {
                "cam0": {**deepcopy(CAPTURE_CAMERAS["scene"]), "fps": 15, "label": "Overhead-Kamera"},
                "cam1": {**deepcopy(X5_CAMERA), "fps": 15, "label": "Insta360 X5"},
                # Display uses 4:3; face detection requests the native raw frame.
                "wrist": {**deepcopy(CAPTURE_CAMERAS["wrist"]), "fps": 15},
            },
            "x5_projection": projection_filter(x5_view), "x5_view": x5_view,
        }
    if model_id == "molmoact2":
        if geometry is not None:
            raise ValueError("MolmoAct2 uses its fixed live camera geometry")
        x5_view = load_view()
        return {
            "geometry": "overhead_x5_4x3",
            "training_view_match": "unverified",
            "version": "molmo-overhead-x5-v6",
            "model": model_id,
            "cameras": {
                "cam0": {**deepcopy(CAPTURE_CAMERAS["scene"]),
                         "controls": deepcopy(MOLMO_OVERHEAD_CONTROLS)},
                "cam1": deepcopy(X5_CAMERA),
            },
            "observer_cameras": {"wrist": {**deepcopy(CAPTURE_CAMERAS["wrist"]), "fps": 15}},
            "slots": {"cam0": "observation.images.cam0", "cam1": "observation.images.cam1"},
            "model_view_hw": [378, 378],
            "resize_owner": "molmo_processor",
            "x5_projection": projection_filter(x5_view),
            "x5_view": x5_view,
        }
    raise ValueError(f"No camera profile for {model_id!r}")


def center_crop_box(width: int, height: int) -> tuple[int, int, int, int]:
    unit = min(width // 4, height // 3)
    if unit < 1:
        raise ValueError("Frame is too small for a 4:3 crop")
    w, h = unit * 4, unit * 3
    return (width - w) // 2, (height - h) // 2, w, h


def crop_4x3(frame, crop=None, *, expected_wh=None):
    """Return an unresampled HWC view, validating capture mode and ROI."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"Expected HWC color image, got {frame.shape}")
    height, width = frame.shape[:2]
    if expected_wh is not None and (width, height) != tuple(expected_wh):
        raise ValueError(f"Expected capture {expected_wh}, got {(width, height)}")
    x, y, w, h = crop if crop is not None else center_crop_box(width, height)
    if (any(not isinstance(v, int) for v in (x, y, w, h))
            or x < 0 or y < 0 or w <= 0 or h <= 0
            or x + w > width or y + h > height or w * 3 != h * 4):
        raise ValueError(f"Invalid 4:3 crop {(x, y, w, h)} for {(width, height)}")
    return frame[y:y + h, x:x + w]
