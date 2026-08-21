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
