#!/usr/bin/env python3
"""Transcribe an audio file or an explicitly requested short microphone capture.

This program does not connect to a robot or issue commands.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "asr" / "qwen3-asr-1.7b"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio", type=Path, help="Existing audio file to transcribe")
    source.add_argument(
        "--record-seconds",
        type=int,
        metavar="N",
        help="Record N seconds from an ALSA microphone (1–30)",
    )
    source.add_argument(
        "--listen",
        action="store_true",
        help="Keep the model loaded; press Enter to capture each 5-second segment",
    )
    parser.add_argument("--alsa-device", default="default", help="ALSA capture device")
    parser.add_argument(
        "--language",
        default="German",
        help="Qwen language name; use Auto for automatic language detection",
    )
    args = parser.parse_args()
    if args.record_seconds is not None and not 1 <= args.record_seconds <= 30:
        parser.error("--record-seconds must be between 1 and 30")
    if args.audio is not None and not args.audio.is_file():
        parser.error(f"audio file does not exist: {args.audio}")
    if not MODEL_PATH.is_dir():
        parser.error(f"model is missing: {MODEL_PATH}; see environments/asr/README.md")
    if not torch.cuda.is_available():
        parser.error("CUDA is unavailable in this process; run on the GPU-enabled host")
    return args


def load_model() -> Qwen3ASRModel:
    from qwen_asr import Qwen3ASRModel

    return Qwen3ASRModel.from_pretrained(
        str(MODEL_PATH),
        dtype=torch.bfloat16,
        device_map="cuda:0",
        max_inference_batch_size=1,
        max_new_tokens=256,
    )


def transcribe(model: Qwen3ASRModel, audio_path: Path, language: str) -> dict[str, str | None]:
    result = model.transcribe(
        audio=str(audio_path),
        language=None if language.lower() == "auto" else language,
    )[0]
    return {"language": result.language, "text": result.text}


def capture(audio_path: Path, seconds: int, alsa_device: str) -> None:
    audio_path.unlink(missing_ok=True)
    command = [
        "arecord",
        "-D", alsa_device,
        "-f", "S16_LE",
        "-r", "16000",
        "-c", "1",
        "-d", str(seconds),
        "-t", "wav",
        str(audio_path),
    ]
    print(f"Recording for {seconds} seconds...", file=sys.stderr)
    subprocess.run(command, check=True)


def show_result(payload: dict[str, str | None]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    args = parse_args()
    model = load_model()
    if args.audio is not None:
        show_result(transcribe(model, args.audio.resolve(), args.language))
    elif args.listen:
        print("Model ready.", file=sys.stderr)
        with tempfile.TemporaryDirectory(prefix="so101-asr-") as temp_dir:
            audio_path = Path(temp_dir) / "microphone.wav"
            while True:
                try:
                    answer = input("Press Enter to record 5 seconds, or q to quit: ").strip().lower()
                except EOFError:
                    break
                if answer == "q":
                    break
                if answer:
                    continue
                capture(audio_path, 5, args.alsa_device)
                show_result(transcribe(model, audio_path, args.language))
    else:
        with tempfile.TemporaryDirectory(prefix="so101-asr-") as temp_dir:
            audio_path = Path(temp_dir) / "microphone.wav"
            capture(audio_path, args.record_seconds, args.alsa_device)
            show_result(transcribe(model, audio_path, args.language))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
