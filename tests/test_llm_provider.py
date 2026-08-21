from __future__ import annotations

import time

import httpx
import pytest

from jobharness.llm import provider as llm


class _FakeResp:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Error response {self.status_code}", request=None, response=self
            )

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, statuses, sleeps, retry_after="2"):
        self.statuses = list(statuses)
        self.calls = 0
        self.sleeps = sleeps
        self.retry_after = retry_after

    def post(self, url, json, headers):
        self.calls += 1
        status = self.statuses.pop(0)
        if status == 429:
            headers = {"Retry-After": self.retry_after} if self.retry_after is not None else {}
            return _FakeResp(429, headers=headers)
        return _FakeResp(200, {"choices": [{"message": {"content": "ok"}}]})


@pytest.fixture(autouse=True)
def _reset_provider_state():
    """Circuit breaker and stats are process-global; isolate each test."""
    llm._breaker.clear()
    for s in llm._stats.values():
        for k in s:
            s[k] = 0
    yield
    llm._breaker.clear()


def test_extract_json_fenced_dict():
    out = llm.extract_json('```json\n{"a": 1}\n```')
    assert out == {"a": 1}


def test_extract_json_plain_dict():
    out = llm.extract_json('prefix {"a": 2} suffix')
    assert out == {"a": 2}


def test_extract_json_plain_dict_with_extra_braces():
    """A dict with nested braces (e.g. a list value) must still parse."""
    out = llm.extract_json('{"a": [1, 2, 3], "b": {"c": "d"}}')
    assert out == {"a": [1, 2, 3], "b": {"c": "d"}}


def test_extract_json_top_level_array():
    """Top-level JSON arrays: current impl returns the first dict found
    (Phase 3.6 makes this robust)."""
    out = llm.extract_json('[{"a": 1}, {"a": 2}]')
    assert out == {"a": 1}


def test_extract_json_empty():
    assert llm.extract_json("") == {}
    assert llm.extract_json("   ") == {}


def test_extract_json_invalid():
    assert llm.extract_json("{invalid}") == {}


def test_extract_json_fenced_array():
    out = llm.extract_json("```json\n[{\"a\": 1}]\n```")
    assert out == {"a": 1}


def test_provider_fallback_chain(monkeypatch):
    """When the requested provider is unconfigured, fall through to others."""

    def fake_cfg(name):
        if name == "gemini":
            return ("", "", "")  # unconfigured
        if name == "glm":
            return ("key", "https://glm.test", "model")
        if name == "qwen":
            return ("", "", "")
        return ("", "", "")

    monkeypatch.setattr(llm, "_provider_cfg", fake_cfg)
    monkeypatch.setattr(llm, "_call_openai_compat", lambda *a, **k: "glm result")

    result = llm.complete("test prompt", provider="gemini")
    assert result == "glm result"


def test_provider_all_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("", "", ""))
    monkeypatch.setattr(llm, "DEFAULT_FALLBACK", ["gemini"])
    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        llm.complete("test", provider="gemini")


def test_provider_unknown_raises(monkeypatch):
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        llm.complete("test", provider="nonexistent")


def test_provider_429_retries_once_then_succeeds(monkeypatch):
    """A 429 is retried once after Retry-After backoff, then the result is used."""
    sleeps: list[float] = []
    client = _FakeClient([429, 200], sleeps)

    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("key", "https://x.test", "model"))
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    result = llm.complete("test", provider="gemini")

    assert result == "ok"
    assert client.calls == 2
    assert sleeps == [2.0]


def test_provider_429_twice_falls_back_to_next(monkeypatch):
    """429 twice on the first provider (default 5s backoff) falls back to the next."""
    sleeps: list[float] = []
    client = _FakeClient([429, 429, 200], sleeps, retry_after=None)

    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("key", "https://x.test", "model"))
    monkeypatch.setattr(llm, "DEFAULT_FALLBACK", ["gemini"])
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    result = llm.complete("test", provider="deepseek")

    assert result == "ok"
    assert client.calls == 3
    assert sleeps == [5.0]


def test_provider_all_429_error_lists_each_provider(monkeypatch):
    """The final error names every attempted provider with its error."""
    sleeps: list[float] = []
    client = _FakeClient([429, 429, 429, 429], sleeps, retry_after=None)

    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("key", "https://x.test", "model"))
    monkeypatch.setattr(llm, "DEFAULT_FALLBACK", ["gemini"])
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(RuntimeError, match=r"deepseek: .*429.*gemini: .*429"):
        llm.complete("test", provider="deepseek")


def test_provider_defaults_applied_when_only_key_set(monkeypatch):
    """A bare GEMINI_API_KEY (no BASE_URL/MODEL envs) is configured via defaults."""
    monkeypatch.setenv("GEMINI_API_KEY", "k-test")
    monkeypatch.delenv("GEMINI_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    api_key, base_url, model = llm._provider_cfg("gemini")
    assert api_key == "k-test"
    assert base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert model == "gemini-2.0-flash"

    calls: list[tuple] = []

    def fake_call(*a, **k):
        calls.append(a)
        return "ok"

    monkeypatch.setattr(llm, "_call_openai_compat", fake_call)
    assert llm.complete("p", provider="gemini") == "ok"
    assert calls  # provider was treated as configured and actually called


def test_circuit_breaker_skips_deepseek_after_three_429s(monkeypatch):
    """3 consecutive 429 failures cool deepseek down; the next complete()
    skips it entirely (attempt count frozen) and falls through to nvidia
    (next in the canonical fallback chain)."""
    sleeps: list[float] = []
    client = _FakeClient([429, 429, 200] * 3 + [200], sleeps, retry_after=None)

    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("key", "https://x.test", "model"))
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    for _ in range(3):
        assert llm.complete("test", provider="deepseek") == "ok"

    st = llm.stats()
    assert st["deepseek"]["attempts"] == 3
    assert st["deepseek"]["rate_limited"] == 3
    assert st["nvidia"]["successes"] == 3

    assert llm.complete("test", provider="deepseek") == "ok"
    st = llm.stats()
    assert st["deepseek"]["attempts"] == 3  # frozen: deepseek was skipped
    assert st["nvidia"]["successes"] == 4
    assert client.calls == 10  # 3*(429,429,200) + 1 nvidia call


def test_complete_skips_cooled_provider_and_uses_next(monkeypatch):
    """complete() returns from the first healthy provider after a cooled one."""
    sleeps: list[float] = []
    client = _FakeClient([429, 429] * 3, sleeps, retry_after=None)

    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("key", "https://x.test", "model"))
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(llm, "DEFAULT_FALLBACK", ["gemini"])

    for _ in range(3):
        with pytest.raises(RuntimeError):
            llm.complete("test", provider="gemini")
    assert llm.stats()["gemini"]["rate_limited"] == 3

    # gemini is now cooled down; a healthy glm should serve the next call.
    monkeypatch.setattr(llm, "DEFAULT_FALLBACK", ["glm"])
    good = _FakeClient([200], sleeps)
    monkeypatch.setattr(llm, "_get_client", lambda: good)

    assert llm.complete("test", provider="gemini") == "ok"
    assert good.calls == 1  # only glm was contacted
    st = llm.stats()
    assert st["gemini"]["attempts"] == 3  # frozen while cooled
    assert st["glm"]["successes"] == 1


def test_all_failed_error_reports_cooled_down(monkeypatch):
    """When every provider fails/cools, the error lists the cooled-down state."""
    sleeps: list[float] = []
    client = _FakeClient([429, 429] * 3, sleeps, retry_after=None)

    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("key", "https://x.test", "model"))
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(llm, "DEFAULT_FALLBACK", ["gemini"])

    for _ in range(3):
        with pytest.raises(RuntimeError):
            llm.complete("test", provider="gemini")

    with pytest.raises(RuntimeError, match="gemini: cooled-down"):
        llm.complete("test", provider="gemini")


def test_stats_reflects_attempts(monkeypatch):
    """stats() tracks attempts/successes/rate_limited per provider."""
    sleeps: list[float] = []
    client = _FakeClient([429, 429, 200, 200], sleeps, retry_after=None)

    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("key", "https://x.test", "model"))
    monkeypatch.setattr(llm, "DEFAULT_FALLBACK", ["gemini"])
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    assert llm.complete("test", provider="deepseek") == "ok"  # deepseek 429x2 -> gemini ok
    assert llm.complete("test", provider="gemini") == "ok"

    st = llm.stats()
    assert st["deepseek"] == {"attempts": 1, "successes": 0, "rate_limited": 1, "good": 0}
    assert st["gemini"] == {"attempts": 2, "successes": 2, "rate_limited": 0, "good": 2}
    assert st["glm"] == {"attempts": 0, "successes": 0, "rate_limited": 0, "good": 0}
    # flat aggregate totals (the shape runner.py logs in its LLM usage line)
    assert st["attempts"] == 3
    assert st["good"] == 2
    assert st["rate_limited"] == 1


def test_nvidia_defaults_applied_when_only_key_set(monkeypatch):
    """A bare NVIDIA_API_KEY (no BASE_URL/MODEL envs) is configured via defaults."""
    monkeypatch.setenv("NVIDIA_API_KEY", "k-test")
    monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
    monkeypatch.delenv("NVIDIA_MODEL", raising=False)

    api_key, base_url, model = llm._provider_cfg("nvidia")
    assert api_key == "k-test"
    assert base_url == "https://integrate.api.nvidia.com/v1"
    assert model == "z-ai/glm-5.2"

    calls: list[tuple] = []

    def fake_call(*a, **k):
        calls.append(a)
        return "ok"

    monkeypatch.setattr(llm, "_call_openai_compat", fake_call)
    assert llm.complete("p", provider="nvidia") == "ok"
    assert calls  # provider was treated as configured and actually called


def test_openrouter_defaults_applied_when_only_key_set(monkeypatch):
    """A bare OPENROUTER_API_KEY (no BASE_URL/MODEL envs) is configured via defaults."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k-test")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    api_key, base_url, model = llm._provider_cfg("openrouter")
    assert api_key == "k-test"
    assert base_url == "https://openrouter.ai/api/v1"
    assert model == "openai/gpt-4o-mini"

    calls: list[tuple] = []

    def fake_call(*a, **k):
        calls.append(a)
        return "ok"

    monkeypatch.setattr(llm, "_call_openai_compat", fake_call)
    assert llm.complete("p", provider="openrouter") == "ok"
    assert calls  # provider was treated as configured and actually called


def test_fallback_chain_canonical_order(monkeypatch):
    """Requested provider first, then the others in canonical order
    [deepseek, nvidia, openrouter, gemini, glm, qwen] with it dropped."""
    attempted: list[str] = []

    def fake_cfg(name):
        return ("key", f"https://{name}.test", "model")

    def fake_call(base_url, *a, **k):
        name = base_url.split("//")[1].split(".")[0]
        attempted.append(name)
        if name == "openrouter":
            return "ok"
        raise httpx.HTTPStatusError("boom", request=None, response=_FakeResp(500))

    monkeypatch.setattr(llm, "_provider_cfg", fake_cfg)
    monkeypatch.setattr(llm, "_call_openai_compat", fake_call)

    # deepseek requested: deepseek fails -> nvidia fails -> openrouter serves
    assert llm.complete("p", provider="deepseek") == "ok"
    assert attempted == ["deepseek", "nvidia", "openrouter"]

    # glm requested: glm first, then canonical order without glm
    attempted.clear()
    assert llm.complete("p", provider="glm") == "ok"
    assert attempted == ["glm", "deepseek", "nvidia", "openrouter"]


def test_default_fallback_chain_constant():
    """All six providers are in the documented canonical chain."""
    assert llm.DEFAULT_FALLBACK == [
        "deepseek",
        "nvidia",
        "openrouter",
        "gemini",
        "glm",
        "qwen",
    ]


def test_stats_preinitialized_for_all_six_providers():
    """stats() has zeroed entries for every provider, with the good alias,
    plus flat top-level totals."""
    st = llm.stats()
    for name in ("deepseek", "nvidia", "openrouter", "gemini", "glm", "qwen"):
        assert st[name] == {"attempts": 0, "successes": 0, "rate_limited": 0, "good": 0}
    assert st["attempts"] == 0
    assert st["good"] == 0
    assert st["rate_limited"] == 0


def test_stats_runner_flat_alias(monkeypatch):
    """runner.py logs _s.get('attempts')/_s.get('good')/_s.get('rate_limited')
    on the flat top level of stats(); make sure those keys exist and total up."""
    monkeypatch.setattr(llm, "_provider_cfg", lambda n: ("key", "https://x.test", "model"))
    monkeypatch.setattr(llm, "_call_openai_compat", lambda *a, **k: "ok")

    assert llm.complete("p", provider="nvidia") == "ok"
    assert llm.complete("p", provider="openrouter") == "ok"

    st = llm.stats()
    assert st["attempts"] == 2
    assert st["good"] == 2
    assert st["rate_limited"] == 0
    assert st["nvidia"]["good"] == st["nvidia"]["successes"] == 1
    assert st["openrouter"]["good"] == st["openrouter"]["successes"] == 1
