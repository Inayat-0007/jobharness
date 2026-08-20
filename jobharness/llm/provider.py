from __future__ import annotations

import json
import re
from typing import Optional

import httpx

from .. import secrets


PROVIDER_ENV = {
    "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL", "GEMINI_MODEL"),
    "glm": ("GLM_API_KEY", "GLM_BASE_URL", "GLM_MODEL"),
    "qwen": ("QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_MODEL"),
}

# Fallback order if a provider fails. Lowest cost first per plan.
DEFAULT_FALLBACK = ["gemini", "glm", "qwen"]


def _provider_cfg(name: str):
    key_env, base_env, model_env = PROVIDER_ENV.get(name, (None, None, None))
    if key_env is None:
        raise ValueError(f"Unknown LLM provider: {name}")
    return secrets.get(key_env), secrets.get(base_env), secrets.get(model_env)


def complete(prompt: str, schema_hint: str = "", provider: str = "gemini", max_tokens: int = 900) -> str:
    """Call an OpenAI-compatible chat completions endpoint.

    Tries the requested provider first, then falls back through the others.
    Raises RuntimeError if all providers are unavailable / unconfigured.
    """
    order = [provider] + [p for p in DEFAULT_FALLBACK if p != provider]
    last_err: Optional[str] = None
    for name in order:
        api_key, base_url, model = _provider_cfg(name)
        if not api_key or not base_url or not model:
            last_err = last_err or f"provider '{name}' not configured"
            continue
        try:
            return _call_openai_compat(base_url, api_key, model, prompt, schema_hint, max_tokens)
        except Exception as e:  # pragma: no cover - network path
            last_err = f"{name}: {e}"
            continue
    raise RuntimeError(f"All LLM providers failed. Last error: {last_err}")


def _call_openai_compat(base_url: str, api_key: str, model: str, prompt: str, schema_hint: str, max_tokens: int) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    system = (
        "You are a strict job-field extractor. Extract ONLY facts present in the provided source text. "
        "If a field is not stated in the text, return the exact string 'MISSING' for that field. "
        "NEVER invent, guess, or infer values. Output ONLY valid JSON matching the requested schema."
    )
    if schema_hint:
        system += f" Schema: {schema_hint}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return ""


def extract_json(text: str) -> dict:
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(candidate)):
        if candidate[i] == "{":
            depth += 1
        elif candidate[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(candidate[start : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}
