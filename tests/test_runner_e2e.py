from __future__ import annotations

from unittest import mock

from jobharness import runner
from jobharness.models import RawJob

import jobharness.sources.api.remoteok as remoteok_mod


def make_raw():
    return [
        RawJob(
            source_name="remoteok",
            source_url="https://remoteok.com/l/1",
            title="Senior Backend Engineer",
            company="Acme",
            location="Remote",
            description="We need a backend engineer with 5 years experience. Python, API.",
            posted_date="2023-11-14",
            apply_url="https://remoteok.com/l/1",
        ),
        RawJob(
            source_name="remoteok",
            source_url="https://example.com/2",
            title="Engineering Manager",
            company="Acme",
            location="Remote",
            description="Lead teams.",
            posted_date="2023-11-14",
            apply_url="https://example.com/2",
        ),
    ]


def _write_profile(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "name: t\nroles: [Backend Engineer]\nkeywords: [python]\nexcludes: [manager]\n"
        "remote: true\nllm_provider: gemini\ntop_n: 5\nsources:\n  remoteok: true\n",
        encoding="utf-8",
    )
    return p


def test_end_to_end_pipeline(tmp_path, monkeypatch):
    profile_path = _write_profile(tmp_path)

    def fake_fetch(self, profile):
        return make_raw()

    monkeypatch.setattr(remoteok_mod.RemoteOKAdapter, "fetch", fake_fetch)
    # Pin to ONLY the remoteok adapter so no network calls occur.
    monkeypatch.setattr(
        "jobharness.runner.enabled_adapters",
        lambda profile: [remoteok_mod.RemoteOKAdapter()],
    )

    def fake_verify(job, check_reachable=True):
        if "Manager" in job.title:
            job.authentic_status = "CLOSED"
        return job

    monkeypatch.setattr("jobharness.runner.verify", lambda job, check_reachable=True: fake_verify(job))
    monkeypatch.setattr("jobharness.runner.telegram", mock.MagicMock(configured=lambda: False))

    from jobharness.profile import load_profile

    prof = load_profile(profile_path)
    result = runner.run_once(
        prof,
        str(tmp_path),
        top_n=5,
        verify_reachable=False,
        use_llm=False,
        push_telegram=False,
    )

    # Backend job matches keyword+role, manager excluded by 'manager' exclude.
    assert result["total_matched"] == 1
    assert result["report"]["total"] == 1
    assert result["pushed"] == 0  # telegram disabled
    assert (tmp_path / "jobs.db").exists()
    assert (tmp_path / "reports").exists()


def test_dry_run_calls_no_push_no_verify(tmp_path, monkeypatch):
    profile_path = _write_profile(tmp_path)
    profile_path.write_text(
        "name: t\nroles: [Backend Engineer]\nkeywords: []\nexcludes: []\n"
        "remote: true\nllm_provider: gemini\ntop_n: 5\nsources:\n  remoteok: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(remoteok_mod.RemoteOKAdapter, "fetch", lambda self, p: make_raw()[:1])
    monkeypatch.setattr(
        "jobharness.runner.enabled_adapters",
        lambda profile: [remoteok_mod.RemoteOKAdapter()],
    )
    monkeypatch.setattr("jobharness.runner.telegram", mock.MagicMock(configured=lambda: False))

    from jobharness.profile import load_profile

    prof = load_profile(profile_path)
    result = runner.run_once(
        prof, str(tmp_path), top_n=5, verify_reachable=False, use_llm=False, push_telegram=False
    )
    assert result["total_matched"] >= 1
    assert result["pushed"] == 0
