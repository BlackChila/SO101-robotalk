#!/usr/bin/env python3
"""Text-only Qwen3.8-27B-FP8 dialogue worker; deliberately has no robot imports."""

import argparse
import contextlib
import json
import sys
from pathlib import Path

import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

from robot_conversation_persona import ROBOT_PERSONA, VOICE_ONLY


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "conversation" / "qwen3.8-27b-fp8"
SYSTEM = ROBOT_PERSONA + VOICE_ONLY


def load():
    if not MODEL.is_dir() or not any(MODEL.glob("*.safetensors")):
        raise RuntimeError(f"Qwen3.8-27B-FP8 model is not installed at {MODEL}")
    with contextlib.redirect_stdout(sys.stderr):
        processor = AutoProcessor.from_pretrained(str(MODEL), local_files_only=True)
        model = AutoModelForMultimodalLM.from_pretrained(
            str(MODEL), device_map="cuda:0", attn_implementation="sdpa",
            local_files_only=True,
        ).eval()
    return processor, model


def reply(processor, model, text: str, history: list[dict]) -> dict:
    if not text.strip() or len(text) > 500:
        raise ValueError("Text must contain 1 to 500 characters")
    messages = [{"role": "system", "content": SYSTEM}]
    for item in history[-12:]:
        if item.get("role") not in {"user", "assistant"} or not isinstance(item.get("content"), str):
            raise ValueError("Invalid conversation history")
        messages.append({"role": item["role"], "content": item["content"][:500]})
    messages.append({"role": "user", "content": text})
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt", enable_thinking=False,
    ).to(model.device)
    with torch.inference_mode(), contextlib.redirect_stdout(sys.stderr):
        outputs = model.generate(**inputs, max_new_tokens=128, do_sample=True,
                                 temperature=0.7, top_p=0.8)
    answer = processor.decode(outputs[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
    answer = answer.split("</think>")[-1].strip()
    if not answer:
        raise RuntimeError("Qwen3.8-27B returned an empty answer")
    return {"reply": answer[:500]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    processor, model = load()
    if args.sample:
        print(reply(processor, model, "Hallo Roboter. Wie geht es dir?", []))
        return
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = reply(processor, model, request["text"], request.get("history", []))
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
