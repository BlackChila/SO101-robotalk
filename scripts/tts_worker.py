#!/usr/bin/env python3
"""Isolated, local Qwen3-TTS CustomVoice JSON-line worker; no robot imports."""

import argparse
import contextlib
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "tts" / "qwen3-tts-1.7b-customvoice"
SPEAKERS = {"Ryan", "Aiden", "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ono_Anna", "Sohee"}


def load():
    if not MODEL.is_dir() or not any(MODEL.glob("*.safetensors")):
        raise RuntimeError(f"TTS model is not installed at {MODEL}")
    with contextlib.redirect_stdout(sys.stderr):
        from qwen_tts import Qwen3TTSModel
        return Qwen3TTSModel.from_pretrained(str(MODEL), device_map="cuda:0", dtype=torch.bfloat16)


def speak(model, text: str, speaker: str, path: Path, language: str = "German") -> dict:
    if not text.strip() or len(text) > 500:
        raise ValueError("Text must contain 1 to 500 characters")
    if speaker not in SPEAKERS:
        raise ValueError("Unknown CustomVoice speaker")
    if language not in {"German", "English"}:
        raise ValueError("Unsupported speech language")
    with torch.inference_mode(), contextlib.redirect_stdout(sys.stderr):
        waves, sample_rate = model.generate_custom_voice(text=text, language=language, speaker=speaker)
    wave = np.asarray(waves[0])
    if wave.size == 0 or not np.isfinite(wave).all():
        raise RuntimeError("TTS produced invalid audio")
    sf.write(path, wave, sample_rate)
    return {"sampleRate": sample_rate, "seconds": round(len(wave) / sample_rate, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path)
    args = parser.parse_args()
    model = load()
    if args.sample:
        print(speak(model, "Guten Morgen, ich bin dein Roboter.", "Ryan", args.sample))
        return
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = speak(model, request["text"], request.get("speaker", "Ryan"), Path(request["path"]), request.get("language", "German"))
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
