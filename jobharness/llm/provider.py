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
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_BASE_URL", "NVIDIA_MODEL"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL"),
}

# Documented defaults (see .env.example). A bare API key is enough to be
# considered configured; these fill in BASE_URL / MODEL when unset.
PROVIDER_DEFAULTS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
    "glm": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "z-ai/glm-5.2"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
}

# Fallback order if a provider fails. complete() tries the requested provider
# first, then the others in this canonical order (requested one dropped).
DEFAULT_FALLBACK = ["deepseek", "nvidia", "openrouter", "gemini", "glm", "qwen"]

# Circuit breaker: after CIRCUIT_THRESHOLD consecutive 429 failures a provider
# is cooled down for CIRCUIT_COOLDOWN_S and skipped by complete().
CIRCUIT_THRESHOLD = 3
CIRCUIT_COOLDOWN_S = 300.0

_state_lock = threading.Lock()
# provider -> {"fails": consecutive-429 count, "cooled_until": monotonic ts}
_breaker: dict[str, dict[str, float]] = {}
# provider -> {"attempts": n, "successes": n, "rate_limited": n}
_stats: dict[str, dict[str, int]] = {
    name: {"attempts": 0, "successes": 0, "rate_limited": 0} for name in PROVIDER_ENV
}


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
    default_base, default_model = PROVIDER_DEFAULTS.get(name, ("", ""))
    api_key = secrets.get(env[0])
    base_url = secrets.get(env[1]) or default_base
    model = secrets.get(env[2]) or default_model
    return api_key, base_url, model


def _is_cooled(name: str) -> bool:
    """True if the provider is inside its 429 cooldown window (thread-safe).

    An expired entry is cleared so the provider gets another chance.
    """
    with _state_lock:
        entry = _breaker.get(name)
        if not entry or not entry["cooled_until"]:
            return False
        if time.monotonic() < entry["cooled_until"]:
            return True
        # cooldown expired -> reset, give the provider another chance
        _breaker.pop(name, None)
        return False


def _record_success(name: str) -> None:
    with _state_lock:
        _stats.setdefault(name, {"attempts": 0, "successes": 0, "rate_limited": 0})["successes"] += 1
        _breaker.pop(name, None)


def _record_failure(name: str, exc: Exception) -> None:
    is_429 = (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and exc.response.status_code == 429
    )
    with _state_lock:
        entry = _breaker.setdefault(name, {"fails": 0, "cooled_until": 0.0})
        if is_429:
            _stats.setdefault(name, {"attempts": 0, "successes": 0, "rate_limited": 0})[
                "rate_limited"
            ] += 1
            entry["fails"] += 1
            if entry["fails"] >= CIRCUIT_THRESHOLD:
                entry["cooled_until"] = time.monotonic() + CIRCUIT_COOLDOWN_S
                logger.warning(
                    "LLM provider %s cooled down for %.0fs after %d consecutive 429s",
                    name,
                    CIRCUIT_COOLDOWN_S,
                    entry["fails"],
                )
        else:
            entry["fails"] = 0


def stats() -> dict[str, dict[str, int] | int]:
    """Per-provider counters for this process, plus flat aggregate totals.

    Per provider: attempts/successes/rate_limited, plus a ``good`` alias for
    successes. The top level also exposes aggregate ``attempts`` / ``good`` /
    ``rate_limited`` totals -- the flat shape jobharness.runner reads for its
    "LLM usage: X calls, Y ok, Z rate-limited" summary line.
    """
    with _state_lock:
        out: dict[str, dict[str, int] | int] = {}
        totals = {"attempts": 0, "successes": 0, "rate_limited": 0}
        for name, s in _stats.items():
            entry = dict(s)
            entry["good"] = entry["successes"]
            out[name] = entry
            for k in totals:
                totals[k] += s[k]
        out["attempts"] = totals["attempts"]
        out["good"] = totals["successes"]
        out["rate_limited"] = totals["rate_limited"]
        return out


def complete(prompt: str, schema_hint: str = "", provider: str = "gemini", max_tokens: int = 900) -> str:
    """Call an OpenAI-compatible chat completions endpoint.

    Tries the requested provider first, then falls back through the others.
    Providers cooled down by the 429 circuit breaker are skipped.
    Raises RuntimeError if all providers are unavailable / unconfigured.
    """
    order = [provider] + [p for p in DEFAULT_FALLBACK if p != provider]
    errors: dict[str, str] = {}
    for name in order:
        api_key, base_url, model = _provider_cfg(name)
        if not api_key or not base_url or not model:
            errors[name] = "not configured"
            continue
        if _is_cooled(name):
            errors[name] = f"cooled-down after {CIRCUIT_THRESHOLD} consecutive 429s"
            continue
        with _state_lock:
            _stats.setdefault(name, {"attempts": 0, "successes": 0, "rate_limited": 0})["attempts"] += 1
        try:
            result = _call_openai_compat(base_url, api_key, model, prompt, schema_hint, max_tokens)
        except Exception as e:  # pragma: no cover - network path
            errors[name] = str(e)
            _record_failure(name, e)
            continue
        _record_success(name)
        return result
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
