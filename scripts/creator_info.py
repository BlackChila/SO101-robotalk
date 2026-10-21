"""Curated creator attribution; no live profile fetch or hardware access."""

from __future__ import annotations

import json
from pathlib import Path


REFERENCE_PATH = Path(__file__).resolve().parents[1] / "docs" / "creator-info.md"
MAX_CREATOR_INFO_WORDS = 350
MAX_CREATOR_INFO_BYTES = 6_000

CREATOR_INFO_TOOL_DESCRIPTION = (
    "Read concise information about who built this RoboTalk project, software and "
    "interactive setup, its creator Eleni Kofekidou / BlackChila, and her supplied "
    "professional background. Excludes contact information and personal details. "
    "Use for explicit creator/author questions such as 'Who built "
    "this setup?', 'Who created this project?', 'Wer hat dieses Setup entwickelt?' "
    "or 'Wer steckt hinter diesem Projekt?'. This credits the setup/software, not "
    "the SO-101 hardware design. For hardware origins, model sizes or architecture "
    "use get_project_info. Do not use for greetings, generic identity or capability "
    "questions, scene questions or movement requests. Reuse an existing result for "
    "follow-ups rather than repeatedly fetching. Read-only; no connected arm needed."
)

CREATOR_INFO_INSTRUCTIONS = (
    "Bei ausdrücklichen Fragen, wer dieses Projekt, Software-Setup oder diese "
    "interaktive Installation gebaut/entwickelt hat, nutze get_creator_info. "
    "Auch Fragen zur Person dahinter, zu BlackChila/Eleni oder ihrem Profil gehören "
    "dazu. Bei einem mehrdeutigen ‚Wer hat dich gebaut?‘ unterscheide mein "
    "interaktives Setup vom SO-101-Hardwaredesign; schreibe der Projektperson nicht "
    "die Entwicklung des Hardwaredesigns oder fremder Modelle zu. Nutze für rein "
    "technische Modell-/Architekturfragen und ausdrücklich erfragte Hardwareherkunft "
    "get_project_info. Rufe nicht beide Werkzeuge für dieselbe reine Urheberfrage auf. "
    "Warte auf das Ergebnis und antworte nur auf den erfragten Aspekt in ein bis "
    "drei kurzen Sätzen in der Gesprächssprache, ohne ungefragte Biografie. Nutze "
    "vorhandene Ergebnisse für Nachfragen weiter. Nenne keine Kontaktangaben, "
    "Profil-Links oder privaten Details. Konzentriere dich auf relevante "
    "Berufserfahrung; ältere Stationen nur, wenn sie wichtig für die Frage oder "
    "die fachliche Entwicklung sind. Beachte Quellen- und Aktualitätsgrenzen; "
    "erfinde keine Berufsbezeichnungen, Arbeitgeber oder Abschlüsse. Kein Aufruf "
    "bei Begrüßungen, allgemeinen Identitätsfragen oder Bewegungsaufträgen. "
)


def get_creator_info() -> dict:
    result = {"status": "available", "background": REFERENCE_PATH.read_text(encoding="utf-8")}
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.split()) > MAX_CREATOR_INFO_WORDS or len(encoded.encode("utf-8")) > MAX_CREATOR_INFO_BYTES:
        raise RuntimeError("Creator information exceeds the compact context limit.")
    return result
