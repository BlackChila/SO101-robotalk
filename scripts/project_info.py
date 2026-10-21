"""Small, curated background lookup; no model, network or hardware operations."""

from __future__ import annotations

import json
from pathlib import Path


REFERENCE_PATH = Path(__file__).resolve().parents[1] / "docs" / "project-info.md"
MAX_PROJECT_INFO_WORDS = 900
MAX_PROJECT_INFO_BYTES = 12_000

PROJECT_INFO_TOOL_DESCRIPTION = (
    "Read concise, verified background about this SO-101 project's technical setup, "
    "models, architecture, purpose, Hugging Face, LeRobot and The Robot Studio. "
    "Only use for explicit technical background/setup questions, e.g. 'technische "
    "Hintergrundinformationen', 'technische Background-Informationen', 'Wie funktioniert "
    "dein technisches Setup?', or which models/parameter counts power this robot. "
    "Do not use for greetings, ordinary conversation, generic capability questions, "
    "visible-scene questions or movement requests. Reuse a previous result for follow-ups "
    "while it remains in context; do not repeatedly fetch the same background. "
    "For who built this software/setup or questions about its creator use get_creator_info instead. "
    "Read-only; works without a connected arm."
)

PROJECT_INFO_INSTRUCTIONS = (
    "Nutze get_project_info nur bei ausdrücklichen Fragen zu deinem technischen Setup, "
    "technischen Hintergrundinformationen/Background-Informationen, den verwendeten "
    "Modellen oder der technischen Herkunft und dem Zweck dieses Projekts. Auch "
    "englische technische Fragen zählen. Nicht bei Begrüßungen, Smalltalk, allgemeinen "
    "Fähigkeitsfragen, Szenenfragen oder Bewegungsaufträgen aufrufen. Warte vor konkreten "
    "Setup-Fakten auf das Ergebnis. Nutze vorhandene Ergebnisse für technische "
    "Nachfragen weiter, solange sie im Kontext stehen; keine wiederholten Abrufe. "
    "Antworte nur auf den erfragten Aspekt in ein bis drei kurzen Sätzen in der "
    "Gesprächssprache. Lies niemals den ganzen Hintergrund vor und biete keinen "
    "ungefragten Technikvortrag an. Unterscheide aktive Gesprächskonfiguration, "
    "alternative Komponenten und dokumentierte Referenzhardware. Keine unbekannten "
    "Parameterzahlen oder ungeprüfte Modellladezustände erfinden. Technisches Wissen "
    "ist keine Erlaubnis für Roboterbewegungen. "
)


def get_project_info(mode: str, *, dialogue_model: str | None = None,
                     realtime_model: str | None = None, voice: str | None = None) -> dict:
    """Return at most two pages, with configuration supplied by the calling session.

    Configured does not mean loaded. Unknown model IDs deliberately have no inferred
    parameter count; the notes describe the repository's reference installation.
    """
    if mode not in {"realtime", "piper", "qwen"}:
        raise ValueError("Unknown conversation mode.")
    if mode == "realtime":
        active = {
            "mode": "ChatGPT Realtime",
            "dialogue": {"model": realtime_model, "parametersBillions": None,
                         "note": "Cloud-Sprachmodell; Parameterzahl hier nicht öffentlich belegt."},
            "speechRecognition": "OpenAI Realtime; zusätzliche Eingabetranskription: gpt-4o-mini-transcribe",
            "speechOutput": "OpenAI Realtime Audio; Piper und Qwen-TTS sind hier nicht die Sprachausgabe.",
        }
    else:
        known_counts = {"qwen/qwen3.8-27b": 27, "Qwen/Qwen3.8-27B": 27}
        active = {
            "mode": "Lokal · Piper" if mode == "piper" else "Lokal · Qwen",
            "dialogue": {"model": dialogue_model,
                         "parametersBillions": known_counts.get(dialogue_model),
                         "note": "Konfigurierter LM-Studio-Modellschlüssel; kein Live-Ladecheck. "
                                 "Q4_K_M ist die Referenzquantisierung, nicht live geprüft."},
            "speechRecognition": {"model": "Qwen3-ASR-1.7B", "parametersBillions": 1.7},
            "speechOutput": ({"engine": "Piper", "device": "CPU", "parametersBillions": None,
                              "note": "Sprachsynthese, kein Dialog-LLM; Größe hängt von der Stimme ab."}
                             if mode == "piper" else
                             {"model": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
                              "parametersBillions": 1.7, "device": "CUDA"}),
        }
    if voice:
        active["voice"] = voice
    result = {"status": "available", "activeConversation": active,
              "background": REFERENCE_PATH.read_text(encoding="utf-8")}
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.split()) > MAX_PROJECT_INFO_WORDS or len(encoded.encode("utf-8")) > MAX_PROJECT_INFO_BYTES:
        raise RuntimeError("Technical background exceeds the compact context limit.")
    return result
