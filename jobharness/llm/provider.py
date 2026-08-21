from __future__ import annotations

import json
import logging
import re
import threading
import time

import httpx

from .. import secrets

logger = logging.getLogger(__name__)

_client: httpx.Client | None = None
_client_lock = threading.Lock()

PROVIDER_ENV = {
    "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL", "GEMINI_MODEL"),
    "glm": ("GLM_API_KEY", "GLM_BASE_URL", "GLM_MODEL"),
    "qwen": ("QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_MODEL"),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"),
}

# Fallback order if a provider fails. Lowest cost first per plan.
DEFAULT_FALLBACK = ["gemini", "glm", "qwen"]


def _get_client() -> httpx.Client:
    """Module-level pooled client, created lazily on first use (thread-safe)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(timeout=60.0)
    return _client


def _provider_cfg(name: str):
    env = PROVIDER_ENV.get(name)
    if env is None:
        raise ValueError(f"Unknown LLM provider: {name}")
    return secrets.get(env[0]), secrets.get(env[1]), secrets.get(env[2])


def complete(prompt: str, schema_hint: str = "", provider: str = "gemini", max_tokens: int = 900) -> str:
    """Call an OpenAI-compatible chat completions endpoint.

    Tries the requested provider first, then falls back through the others.
    Raises RuntimeError if all providers are unavailable / unconfigured.
    """
    order = [provider] + [p for p in DEFAULT_FALLBACK if p != provider]
    errors: dict[str, str] = {}
    for name in order:
        api_key, base_url, model = _provider_cfg(name)
        if not api_key or not base_url or not model:
            errors[name] = "not configured"
            continue
        try:
            return _call_openai_compat(base_url, api_key, model, prompt, schema_hint, max_tokens)
        except Exception as e:  # pragma: no cover - network path
            errors[name] = str(e)
            continue
    detail = ", ".join(f"{name}: {err}" for name, err in errors.items())
    raise RuntimeError(f"All LLM providers failed. Errors: {detail}")


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
    client = _get_client()
    resp = client.post(url, json=payload, headers=headers)
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "")
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            delay = 5.0
        logger.warning("LLM provider rate-limited (429), retrying in %.1fs", delay)
        time.sleep(delay)
        resp = client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            logger.warning("LLM provider still rate-limited (429) after retry")
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
    if start != -1:
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
    # No balanced object found: try the whole candidate, which may be a
    # top-level JSON array (e.g. the model returned a list of field dicts).
    try:
        parsed = json.loads(candidate.strip())
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        return parsed[0]
    return {}
