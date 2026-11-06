"""Thin wrappers around the Gemini and DeepSeek REST APIs. Both return parsed JSON."""
import json
import re
import time

import httpx

from config import settings


class LLMError(Exception):
    pass


def _parse_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError("Model did not return valid JSON")


def _post(url, headers, payload):
    last = None
    for attempt in range(3):
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=90)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
    raise LLMError(f"API call failed: {last}")


def gemini_json(prompt: str) -> dict:
    if not settings.gemini_key:
        raise LLMError("GEMINI_API_KEY is missing")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    data = _post(
        url,
        {"x-goog-api-key": settings.gemini_key, "Content-Type": "application/json"},
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        },
    )
    try:
        return _parse_json(data["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError):
        raise LLMError(f"Unexpected Gemini response: {str(data)[:200]}")


def deepseek_json(prompt: str) -> dict:
    if not settings.deepseek_key:
        raise LLMError("DEEPSEEK_API_KEY is missing")
    data = _post(
        "https://api.deepseek.com/chat/completions",
        {"Authorization": f"Bearer {settings.deepseek_key}", "Content-Type": "application/json"},
        {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": "You are a careful research assistant. Reply with JSON only."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        },
    )
    try:
        return _parse_json(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError):
        raise LLMError(f"Unexpected DeepSeek response: {str(data)[:200]}")


def ask(provider: str, prompt: str) -> dict:
    """Call the preferred model; fall back to the other one if its key is missing."""
    has_g, has_d = bool(settings.gemini_key), bool(settings.deepseek_key)
    if provider == "gemini" and not has_g and has_d:
        provider = "deepseek"
    elif provider == "deepseek" and not has_d and has_g:
        provider = "gemini"
    return gemini_json(prompt) if provider == "gemini" else deepseek_json(prompt)
