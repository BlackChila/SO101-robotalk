"""LM Studio adapters for legacy text chat and local robot tool dialogue."""

from __future__ import annotations

import json
import os
import threading
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from robot_conversation_persona import ROBOT_PERSONA, VOICE_ONLY, OPENING_PROMPT


BASE_URL = os.environ.get("SO101_LM_STUDIO_URL", "http://172.17.0.1:1234").rstrip("/")
MODEL = os.environ.get("SO101_CONVERSATION_MODEL", "qwen/qwen3.8-27b")
_load_lock = threading.Lock()
SYSTEM = ROBOT_PERSONA + VOICE_ONLY


def _request(path: str, payload: dict | None = None, timeout: float = 5) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token := os.environ.get("SO101_LM_STUDIO_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = Request(BASE_URL + path, data=data, headers=headers,
                      method="POST" if data is not None else "GET")
    try:
        # LM Studio is local, and this host's bridge address must bypass shell proxies.
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"LM Studio HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"LM Studio ist nicht erreichbar: {exc}") from exc


def model_status() -> dict:
    """Report whether the configured model is loaded, including its quantization."""
    try:
        models = _request("/api/v1/models")["models"]
    except (RuntimeError, KeyError, ValueError):
        return {"ready": False, "model": MODEL, "reason": "LM Studio API nicht erreichbar"}
    for model in models:
        instances = model.get("loaded_instances") or []
        if model.get("key") == MODEL or any(item.get("id") == MODEL for item in instances):
            quant = (model.get("quantization") or {}).get("name")
            return {"ready": bool(instances), "model": MODEL,
                    "quantization": quant, "loaded": bool(instances),
                    "reason": "" if instances else f"{MODEL} muss in LM Studio geladen sein"}
    return {"ready": False, "model": MODEL,
            "reason": f"{MODEL} ist in LM Studio nicht installiert"}


def ensure_model_loaded() -> dict:
    """Load the locally installed dialogue model only when it is absent from memory."""
    with _load_lock:
        try:
            models = _request("/api/v1/models")["models"]
        except (KeyError, ValueError) as exc:
            raise RuntimeError("LM Studio lieferte keine Modellliste.") from exc
        selected = next((model for model in models if model.get("key") == MODEL), None)
        if selected is None:
            raise RuntimeError(f"{MODEL} ist in LM Studio nicht installiert.")
        if not selected.get("loaded_instances"):
            loaded = _request("/api/v1/models/load", {"model": MODEL}, timeout=180)
            if loaded.get("status") != "loaded":
                raise RuntimeError(f"LM Studio konnte {MODEL} nicht laden.")
        result = model_status()
        if not result["ready"]:
            raise RuntimeError(result["reason"])
        return result


def reply(text: str, previous_response_id: str | None = None) -> dict:
    if not text.strip() or len(text) > 500:
        raise ValueError("Text must contain 1 to 500 characters")
    if previous_response_id is not None and not previous_response_id.startswith("resp_"):
        raise ValueError("Invalid previous response ID")
    payload = {"model": MODEL, "input": text, "system_prompt": SYSTEM,
               "reasoning": "off", "max_output_tokens": 160, "store": True}
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    result = _request("/api/v1/chat", payload, timeout=120)
    answer = "\n".join(item["content"] for item in result.get("output", [])
                       if item.get("type") == "message" and isinstance(item.get("content"), str)).strip()
    response_id = result.get("response_id")
    if not answer or not isinstance(response_id, str) or not response_id.startswith("resp_"):
        raise RuntimeError("LM Studio lieferte keine vollständige Antwort")
    return {"reply": answer, "responseId": response_id}


def greet() -> dict:
    """Start Qwen TTS dialogue with a real input turn and stored continuation."""
    return reply(OPENING_PROMPT + " Use German for this opening greeting.")


def tool_reply(messages: list[dict], tools: list[dict]) -> dict:
    """Local robot dialogue; the application owns history and executes tools."""
    payload = {"model": MODEL, "messages": messages, "stream": False,
               "temperature": 0.2, "max_tokens": 512,
               "reasoning_effort": "none",
               "tools": tools, "tool_choice": "auto" if tools else "none",
               "parallel_tool_calls": False}
    result = _request("/v1/chat/completions", payload, timeout=120)
    choices = result.get("choices") or []
    if not choices or choices[0].get("finish_reason") not in {"stop", "tool_calls"}:
        raise RuntimeError("Lokales Modell lieferte keine vollständige Antwort/Werkzeuganfrage.")
    message = choices[0].get("message") or {}
    # Do not speak reasoning or attempt to interpret malformed tool text as code.
    return {"role": "assistant", "content": message.get("content") or "",
            **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {})}
