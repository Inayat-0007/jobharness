from __future__ import annotations

from unittest import mock

from jobharness import runner
from jobharness.fetcher import classify_response
from jobharness.evidence.source import SourceStatus
from jobharness.sources.base import SourceAdapter
from jobharness.sources.exceptions import (
    RateLimitedError,
    AuthRequiredError,
    SourceDownError,
    ParseFailureError,
)
from jobharness.models import RawJob
from jobharness.profile import Profile


class _Resp:
    def __init__(self, status, text=""):
        self.status_code = status
        self._text = text

    @property
    def text(self):
        return self._text


def test_classify_response_mapping():
    assert classify_response(_Resp(200)) is None
    assert classify_response(_Resp(429)) is SourceStatus.RATE_LIMITED
    assert classify_response(_Resp(401)) is SourceStatus.AUTH_REQUIRED
    assert classify_response(_Resp(500)) is SourceStatus.SOURCE_DOWN
    assert classify_response(_Resp(403)) is SourceStatus.BLOCKED
    assert classify_response(_Resp(200, "verify you are human")) is SourceStatus.BLOCKED


class _FakeAdapter(SourceAdapter):
    name = "fake"

    def __init__(self, behavior):
        self._behavior = behavior

    def fetch(self, profile):
        return self._behavior(profile)


def _profile(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "name: t\nroles: [Backend Engineer]\nkeywords: [python]\n"
        "remote: true\nllm_provider: gemini\ntop_n: 5\nsources:\n  fake: true\n",
        encoding="utf-8",
    )
    from jobharness.profile import load_profile

    return load_profile(p)


def _run(tmp_path, behavior):
    prof = _profile(tmp_path)
    adapter = _FakeAdapter(behavior)
    monkeypatch_like = mock.patch(
        "jobharness.runner.enabled_adapters", lambda profile: [adapter]
    )
    with monkeypatch_like:
        with mock.patch("jobharness.runner.telegram", mock.MagicMock(configured=lambda: False)):
            return runner.run_once(
                prof, str(tmp_path), top_n=5, verify_reachable=False, use_llm=False, push_telegram=False
            )


def test_runner_maps_typed_exception_to_status(tmp_path):
    def boom(profile):
        raise RateLimitedError("rate limited")

    result = _run(tmp_path, boom)
    assert result["source_statuses"] == {"fake": "rate_limited"}


def test_runner_maps_all_typed_exceptions(tmp_path):
    for exc, expected in [
        (AuthRequiredError("x"), "auth_required"),
        (SourceDownError("x"), "source_down"),
        (ParseFailureError("x"), "parse_failure"),
    ]:
        result = _run(tmp_path, lambda profile, e=exc: (_ for _ in ()).throw(e))
        assert result["source_statuses"] == {"fake": expected}


def test_runner_maps_generic_exception_to_source_down(tmp_path):
    result = _run(tmp_path, lambda profile: (_ for _ in ()).throw(RuntimeError("boom")))
    assert result["source_statuses"] == {"fake": "source_down"}
    assert any("boom" in e for e in result["errors"])


def test_runner_empty_source_is_empty_and_blocked(tmp_path):
    result = _run(tmp_path, lambda profile: [])
    assert result["source_statuses"] == {"fake": "empty"}
    assert "fake" in result["blocked"]


def test_runner_ok_source_with_no_matches(tmp_path):
    def fetch(profile):
        return [
            RawJob(
                source_name="fake", source_url="https://x.com/1",
                title="Engineering Manager", company="Acme", location="Remote",
                description="lead teams", posted_date="2023-11-14",
                apply_url="https://x.com/1",
            )
        ]

    result = _run(tmp_path, fetch)
    assert result["source_statuses"] == {"fake": "no_match"}
    assert result["total_matched"] == 0


def test_runner_ok_source_with_matches(tmp_path):
    def fetch(profile):
        return [
            RawJob(
                source_name="fake", source_url="https://x.com/1",
                title="Backend Engineer", company="Acme", location="Remote",
                description="python api backend", posted_date="2023-11-14",
                apply_url="https://x.com/1",
            )
        ]

    result = _run(tmp_path, fetch)
    assert result["source_statuses"] == {"fake": "ok"}
    assert result["total_matched"] == 1
