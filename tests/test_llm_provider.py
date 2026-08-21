from __future__ import annotations

import json
from unittest import mock

from jobharness.llm import provider as llm


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
    calls = []

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
    try:
        llm.complete("test", provider="gemini")
        assert False, "should have raised"
    except RuntimeError as e:
        assert "All LLM providers failed" in str(e)


def test_provider_unknown_raises(monkeypatch):
    try:
        llm.complete("test", provider="nonexistent")
        assert False, "should have raised"
    except ValueError as e:
        assert "Unknown LLM provider" in str(e)