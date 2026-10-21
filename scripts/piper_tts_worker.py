#!/usr/bin/env python3
"""Persistent CPU Piper worker for local conversation speech; no robot imports."""

import argparse
import json
import sys
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "tts" / "piper" / "de_DE-thorsten-medium.onnx"
VOICES = {
    "Thorsten": MODEL,
    "Kerstin": ROOT / "models" / "tts" / "piper" / "de_DE-kerstin-low.onnx",
    "Amy": ROOT / "models" / "tts" / "piper" / "en_US-amy-medium.onnx",
    "Ryan": ROOT / "models" / "tts" / "piper" / "en_US-ryan-medium.onnx",
    "Alan": ROOT / "models" / "tts" / "piper" / "en_GB-alan-medium.onnx",
    "Jenny": ROOT / "models" / "tts" / "piper" / "en_GB-jenny_dioco-medium.onnx",
}


def load(name: str = "Thorsten"):
    from piper import PiperVoice

    if name not in VOICES:
        raise ValueError("Unknown Piper voice")
    model = VOICES[name]
    if not model.is_file() or not model.with_suffix(".onnx.json").is_file():
        raise RuntimeError(f"Piper voice is not installed at {model}")
    return PiperVoice.load(str(model))


def speak(voice, text: str, path: Path) -> dict:
    if not text.strip() or len(text) > 500:
        raise ValueError("Text must contain 1 to 500 characters")
    with wave.open(str(path), "wb") as output:
        voice.synthesize_wav(text, output)
    with wave.open(str(path), "rb") as output:
        rate = output.getframerate()
        frames = output.getnframes()
    if not frames:
        raise RuntimeError("Piper produced empty audio")
    return {"sampleRate": rate, "seconds": round(frames / rate, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path)
    args = parser.parse_args()
    if args.sample:
        print(json.dumps(speak(load(), "Guten Morgen, ich bin dein Roboter.", args.sample)))
        return
    voices = {}
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            name = request.get("voice", "Thorsten")
            if name not in VOICES:
                raise ValueError("Unknown Piper voice")
            if name not in voices:
                voices[name] = load(name)
            if request.get("op") == "prepare":
                result = {"ready": True}
            else:
                result = speak(voices[name], request["text"], Path(request["path"]))
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
