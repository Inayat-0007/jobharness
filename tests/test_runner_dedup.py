from __future__ import annotations

from unittest import mock

import jobharness.sources.api.remoteok as remoteok_mod
from jobharness import runner
from jobharness.models import RawJob


def _write_profile(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "name: t\nroles: [Backend Engineer]\nkeywords: [python]\nexcludes: [manager]\n"
        "remote: true\nllm_provider: gemini\ntop_n: 5\nsources:\n  remoteok: true\n",
        encoding="utf-8",
    )
    return p


def _same_job_two_sources():
    j = {
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "description": "python api backend engineer 5 years experience",
        "posted_date": "2023-11-14",
        "apply_url": "https://acme.com/j/1",
    }
    return [
        RawJob(source_name="remoteok", source_url="https://acme.com/j/1", **j),
        RawJob(source_name="weworkremotely", source_url="https://acme.com/j/1", **j),
    ]


def test_pre_dedup_collapses_same_job_across_sources(tmp_path, monkeypatch):
    """The same job via two sources must be extracted once (by title+company),
    not twice; the cross-source pre-dedup must NOT include source_name in the key.
    """
    calls = {"n": 0}
    original_extract = runner.extract

    def counting_extract(raw, **kw):
        calls["n"] += 1
        return original_extract(raw, **kw)

    monkeypatch.setattr(remoteok_mod.RemoteOKAdapter, "fetch", lambda self, p: _same_job_two_sources())
    monkeypatch.setattr(
        "jobharness.runner.enabled_adapters",
        lambda profile: [remoteok_mod.RemoteOKAdapter()],
    )
    monkeypatch.setattr("jobharness.runner.extract", counting_extract)
    monkeypatch.setattr("jobharness.runner.telegram", mock.MagicMock(configured=lambda: False))

    from jobharness.profile import load_profile

    prof = load_profile(_write_profile(tmp_path))
    result = runner.run_once(
        prof, str(tmp_path), top_n=5, verify_reachable=False, use_llm=False, push_telegram=False
    )
    # Two raw jobs -> pre-dedup collapses to one -> one extraction, one matched.
    assert result["total_raw"] == 2
    assert calls["n"] == 1
    assert result["total_matched"] == 1
