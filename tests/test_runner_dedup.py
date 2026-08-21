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


def test_pre_dedup_collapses_same_job_across_sources(tmp_path, monkeypatch, caplog):
    """The same job via two sources must be extracted once (by title+company),
    not twice; the cross-source pre-dedup must NOT include source_name in the key.
    The collapse is surfaced at INFO so silent pre-dedup drops are observable.
    """
    caplog.set_level("INFO")
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
    # The collapse is logged (a single key group of size >1 counts once).
    assert "pre-dedup: dropped 1 collapsed key(s)" in caplog.text


def _write_profile2(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "name: t\nroles: [Backend Engineer]\nkeywords: [python]\nexcludes: []\n"
        "remote: true\nllm_provider: gemini\ntop_n: 5\nsources:\n  remoteok: true\n",
        encoding="utf-8",
    )
    return p


def make_job_for_runner(title, company, location, url, source="remoteok", **kw):
    from jobharness.models import RawJob
    raw = RawJob(
        source_name=source,
        source_url=url,
        title=title,
        company=company,
        location=location,
        description="python api backend engineer 5 years experience",
        posted_date="2026-08-20",
        apply_url=url,
    )
    for k, v in kw.items():
        setattr(raw, k, v)
    return raw


def _run_one(tmp_path, raws, monkeypatch):
    import jobharness.sources.api.remoteok as remoteok_mod

    monkeypatch.setattr(remoteok_mod.RemoteOKAdapter, "fetch", lambda self, p: raws)
    monkeypatch.setattr(
        "jobharness.runner.enabled_adapters",
        lambda profile: [remoteok_mod.RemoteOKAdapter()],
    )
    monkeypatch.setattr("jobharness.runner.telegram", mock.MagicMock(configured=lambda: False))

    from jobharness.profile import load_profile
    prof = load_profile(_write_profile2(tmp_path))
    return runner.run_once(
        prof, str(tmp_path), top_n=5, verify_reachable=False, use_llm=False, push_telegram=False
    )


def test_fuzzy_merge_high_path(tmp_path, monkeypatch):
    """Same job with rewritten title -> HIGH match -> merged, not genuinely_new."""
    url = "https://acme.com/j/1"
    raws1 = [make_job_for_runner("Backend Engineer", "Acme", "Remote", url)]
    raws2 = [make_job_for_runner("Backend Engineer (Remote)", "Acme", "Remote", url)]

    r1 = _run_one(tmp_path, raws1, monkeypatch)
    assert r1["total_matched"] == 1
    assert r1["report"]["new_count"] == 1

    r2 = _run_one(tmp_path, raws2, monkeypatch)
    # Second run: merged, not genuinely new, not in new_count
    assert r2["total_matched"] == 1
    assert r2["report"]["new_count"] == 0


def test_fuzzy_merge_medium_path(tmp_path, monkeypatch):
    """Similar but different location -> MEDIUM -> REVIEW decision + possible_duplicate_of."""
    import json as _json

    url = "https://acme.com/j/1"
    raws1 = [make_job_for_runner("Backend Engineer", "Acme", "Remote", url)]
    raws2 = [make_job_for_runner("Backend Engineer", "Acme", "Austin, TX", url)]

    r1 = _run_one(tmp_path, raws1, monkeypatch)
    assert r1["total_matched"] == 1

    r2 = _run_one(tmp_path, raws2, monkeypatch)
    assert r2["total_matched"] == 1
    # MEDIUM: stored as a new row flagged REVIEW with possible_duplicate_of set.
    with open(r2["report"]["json"], encoding="utf-8") as fh:
        job = _json.load(fh)[0]
    assert job["decision"] == "REVIEW"
    assert job["possible_duplicate_of"]
    assert job["identity_score"] > 0.5


def test_same_run_fuzzy_merge_cross_source(tmp_path, monkeypatch):
    """Two sources sight the same job with slightly different titles in ONE
    run: the in-run linkage must fold the second sighting into the first
    (single stored row, single new count) instead of storing a duplicate."""
    import sqlite3 as _sqlite3

    raws = [
        make_job_for_runner(
            "Backend Engineer", "Acme", "Remote", "https://acme.com/j/1", source="remoteok"
        ),
        make_job_for_runner(
            "Backend Engineer - India",
            "Acme",
            "Remote",
            "https://acme.com/j/2",
            source="weworkremotely",
        ),
    ]
    r1 = _run_one(tmp_path, raws, monkeypatch)
    assert r1["total_raw"] == 2
    assert r1["total_matched"] == 2
    assert r1["report"]["new_count"] == 1
    with _sqlite3.connect(str(tmp_path / "jobs.db")) as conn:
        rows = conn.execute("SELECT title FROM jobs").fetchall()
    assert len(rows) == 1
