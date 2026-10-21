"""Bounded language-model images used only by the look_at_scene tool."""
import base64

import cv2

# One image per event: base64 + labels stays below the common 64 KiB SCTP limit.
MAX_JPEG_BYTES = 40_000


def encode_scene_image(rgb, role: str, captured_at: float) -> dict:
    # Rotate only this language-model copy. Shared capture/policy frames retain
    # their original orientation, including MolmoAct2 inputs and recordings.
    if role == "wrist":
        rgb = cv2.rotate(rgb, cv2.ROTATE_90_CLOCKWISE)
    height, width = rgb.shape[:2]
    for edge in (768, 640, 512, 384, 256):
        scale = min(1.0, edge / max(width, height))
        image = cv2.resize(rgb, (round(width * scale), round(height * scale)),
                           interpolation=cv2.INTER_AREA)
        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        for quality in (75, 60, 45):
            ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if ok and len(encoded) <= MAX_JPEG_BYTES:
                return {"camera": role, "capturedAt": captured_at,
                        "width": image.shape[1], "height": image.shape[0],
                        "imageUrl": "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")}
    raise RuntimeError("The camera image could not be compressed for Realtime.")
