import json
import time

import httpx

from . import config

_BASE = "https://generativelanguage.googleapis.com/v1beta"
_RETRY_STATUS = {429, 503}  # transient: rate-limited or model temporarily overloaded


def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    """messages: [{"role": "user"|"assistant", "content": "..."}] -> Gemini's
    {"role": "user"|"model", "parts": [{"text": ...}]} shape."""
    return [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
    ]


def _generate(system: str, messages: list[dict], max_tokens: int, json_mode: bool) -> str:
    body = {
        "contents": _to_gemini_contents(messages),
        "systemInstruction": {"parts": [{"text": system}]},
        # thinkingBudget=0: these are short, low-stakes generations (chat replies,
        # diary entries) that don't need extended reasoning, and thinking tokens
        # were eating maxOutputTokens before any visible output was produced.
        "generationConfig": {"maxOutputTokens": max_tokens, "thinkingConfig": {"thinkingBudget": 0}},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    max_attempts = 5
    for attempt in range(max_attempts):
        r = httpx.post(
            f"{_BASE}/models/{config.GEMINI_MODEL}:generateContent",
            params={"key": config.GEMINI_API_KEY},
            json=body,
            timeout=30,
        )
        if r.status_code in _RETRY_STATUS and attempt < max_attempts - 1:
            time.sleep(2**attempt)  # 1s, 2s, 4s, 8s
            continue
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def complete(system: str, messages: list[dict], max_tokens: int = 800) -> str:
    return _generate(system, messages, max_tokens, json_mode=False)


def complete_json(system: str, messages: list[dict], max_tokens: int = 800) -> dict:
    text = _generate(system, messages, max_tokens, json_mode=True)
    return json.loads(text)
