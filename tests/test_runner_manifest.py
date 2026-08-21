from __future__ import annotations

import json
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
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


def _raw(title, company, location, url):
    return RawJob(
        source_name="remoteok",
        source_url=url,
        title=title,
        company=company,
        location=location,
        description="python api backend engineer 5 years experience",
        posted_date="2026-08-20",
        apply_url=url,
    )


def _run(tmp_path, monkeypatch, raws, telegram_mock=None, **kwargs):
    monkeypatch.setattr(remoteok_mod.RemoteOKAdapter, "fetch", lambda self, p: raws)
    monkeypatch.setattr(
        "jobharness.runner.enabled_adapters",
        lambda profile: [remoteok_mod.RemoteOKAdapter()],
    )
    if telegram_mock is None:
        telegram_mock = mock.MagicMock(configured=lambda: False)
    monkeypatch.setattr("jobharness.runner.telegram", telegram_mock)

    from jobharness.profile import load_profile

    prof = load_profile(_write_profile(tmp_path))
    kw = dict(top_n=5, verify_reachable=False, use_llm=False, push_telegram=False)
    kw.update(kwargs)
    return runner.run_once(prof, str(tmp_path), **kw)


def _manifest_path(tmp_path, result):
    return tmp_path / "reports" / result["run_ts"] / "manifest.json"


def test_manifest_written_with_stage_timings_and_source_statuses(tmp_path, monkeypatch):
    # Two clearly distinct jobs (different company/location): the in-run fuzzy
    # linkage must NOT merge them, so both are stored as new.
    raws = [
        _raw("Backend Engineer", "Acme", "Remote", "https://acme.com/j/1"),
        _raw("Senior Backend Engineer", "Globex", "Austin, TX", "https://globex.com/j/2"),
    ]
    result = _run(tmp_path, monkeypatch, raws)

    mpath = _manifest_path(tmp_path, result)
    assert mpath.exists()
    m = json.loads(mpath.read_text(encoding="utf-8"))
    assert m["run_ts"] == result["run_ts"]
    assert m["run_started"] < m["run_finished"]
    assert m["wall_clock_seconds"] >= 0
    for stage in ("fetch", "extract", "verify", "enrich", "dedupe", "report", "push"):
        assert stage in m["stages"]
        assert m["stages"][stage] >= 0
    assert m["sources"] == {"remoteok": "ok"}
    assert m["raw_job_count"] == 2
    assert m["matched_count"] == 2
    assert m["new_count"] == 2
    assert m["re_alerted_count"] == 0
    assert m["errors"] == 0
    assert m["llm_budget_used"] == 0
    assert m["timeout"] is False
    assert m["timeout_aborted_stages"] == []


def test_pre_dedup_keeps_same_title_company_in_different_cities(tmp_path, monkeypatch):
    calls = {"n": 0}
    original_extract = runner.extract

    def counting_extract(raw, **kw):
        calls["n"] += 1
        return original_extract(raw, **kw)

    monkeypatch.setattr("jobharness.runner.extract", counting_extract)
    raws = [
        _raw("Backend Engineer", "Acme", "Austin, TX", "https://acme.com/j/austin"),
        _raw("Backend Engineer", "Acme", "New York, NY", "https://acme.com/j/nyc"),
    ]
    result = _run(tmp_path, monkeypatch, raws)
    assert result["total_raw"] == 2
    assert calls["n"] == 2
    assert result["total_matched"] == 2
    assert result["report"]["new_count"] == 2


def test_pre_dedup_key_normalizes_and_buckets():
    a = _raw("Backend Engineer", "Acme", "Austin, TX", "https://a/1")
    b = _raw("Backend Engineer", "Acme", "New York, NY", "https://a/2")
    c = _raw("Backend Engineer", "Acme, Inc.", "Austin, TX", "https://a/3")
    d = _raw("Backend Engineer", "Acme", "Remote", "https://a/4")
    e = _raw("Backend Engineer", "Acme", "Remote (Worldwide)", "https://a/5")
    assert runner._pre_dedup_key(a) != runner._pre_dedup_key(b)
    assert runner._pre_dedup_key(a) == runner._pre_dedup_key(c)
    assert runner._pre_dedup_key(d) == runner._pre_dedup_key(e)


class _SpyExecutor(ThreadPoolExecutor):
    """Records the maximum number of futures in flight at any moment."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_inflight = 0
        self._inflight = 0
        self._lock = threading.Lock()

    def submit(self, fn, *args, **kwargs):
        with self._lock:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)

        def _wrapped():
            try:
                return fn(*args, **kwargs)
            finally:
                with self._lock:
                    self._inflight -= 1

        return super().submit(_wrapped)


def test_extract_verify_dedupe_stages_are_bounded(tmp_path, monkeypatch):
    raws = [
        _raw("Backend Engineer", f"Acme{i}", "Remote", f"https://acme{i}.com/j")
        for i in range(8)
    ]
    pools = []

    def factory(*args, **kwargs):
        ex = _SpyExecutor(*args, **kwargs)
        pools.append(ex)
        return ex

    monkeypatch.setattr("jobharness.runner.ThreadPoolExecutor", factory)
    monkeypatch.setattr("jobharness.runner.verify", lambda job, check_reachable=True: job)

    result = _run(tmp_path, monkeypatch, raws, verify_reachable=True)
    assert result["total_matched"] == 8
    # Pool creation order in run_once: fetch, extract, verify, dedupe.
    _, extract_pool, verify_pool, dedupe_pool = pools
    assert extract_pool.max_inflight <= runner.EXTRACT_WORKERS
    assert verify_pool.max_inflight <= runner.VERIFY_WORKERS
    assert dedupe_pool.max_inflight <= runner.DEDUPE_WORKERS


def test_timeout_aborts_stages_but_still_writes_reports_and_manifest(tmp_path, monkeypatch):
    raws = [_raw("Backend Engineer", "Acme", "Remote", "https://acme.com/j/1")]
    real_monotonic = _time.monotonic
    state = {"base": real_monotonic(), "shifted": False}

    def fake_monotonic():
        # First call (run start) returns real time; every later call is
        # already past the default 60-min deadline, so the extract stage
        # aborts and all remaining stages are skipped.
        if not state["shifted"]:
            state["shifted"] = True
            return state["base"]
        return state["base"] + 36000.0

    monkeypatch.setattr(_time, "monotonic", fake_monotonic)
    monkeypatch.setattr(remoteok_mod.RemoteOKAdapter, "fetch", lambda self, p: raws)
    monkeypatch.setattr(
        "jobharness.runner.enabled_adapters",
        lambda profile: [remoteok_mod.RemoteOKAdapter()],
    )
    monkeypatch.setattr("jobharness.runner.telegram", mock.MagicMock(configured=lambda: False))

    from jobharness.profile import load_profile

    prof = load_profile(_write_profile(tmp_path))
    result = runner.run_once(
        prof, str(tmp_path), top_n=5, verify_reachable=False, use_llm=False, push_telegram=False
    )
    assert result["total_matched"] == 0
    mpath = _manifest_path(tmp_path, result)
    assert mpath.exists()
    m = json.loads(mpath.read_text(encoding="utf-8"))
    assert m["timeout"] is True
    assert "extract" in m["timeout_aborted_stages"]
    assert m["raw_job_count"] == 1
    assert m["matched_count"] == 0
    assert (tmp_path / "reports" / result["run_ts"] / "report.json").exists()


def test_degraded_jobs_pushed_with_warning_and_kept_in_new_count(tmp_path, monkeypatch, caplog):
    """DEGRADED jobs (verification could not confirm reachability - e.g. the
    source rate-limited the verify check) stay in reports and new_count AND
    are pushed to telegram: the listing fetch succeeded so the job is real;
    the card carries a visible unverified-link warning instead of the job
    being silently withheld."""
    caplog.set_level("INFO")
    telegram = mock.MagicMock()
    telegram.configured.return_value = True
    pushed_lists: list[list] = []
    telegram.notify_new.side_effect = lambda jobs: pushed_lists.append(list(jobs)) or len(jobs)
    monkeypatch.setattr("jobharness.runner.telegram", telegram)

    def fake_verify(job, check_reachable=True):
        job.freshness = "fresh"
        if "Senior Backend Engineer" in job.title:
            job.authentic_status = "DEGRADED"
        return job

    monkeypatch.setattr("jobharness.runner.verify", fake_verify)

    raws = [
        _raw("Backend Engineer", "Acme", "Remote", "https://acme.com/j/1"),
        _raw("Senior Backend Engineer", "Globex", "Austin, TX", "https://globex.com/j/2"),
    ]
    result = _run(
        tmp_path, monkeypatch, raws,
        telegram_mock=telegram,
        verify_reachable=True, push_telegram=True,
    )

    # Both genuinely-new jobs are pushed; the DEGRADED one is included
    # (its card carries the warning) and logged as such.
    assert result["pushed"] == 2
    assert len(pushed_lists) == 1
    pushed = pushed_lists[0]
    assert len(pushed) == 2
    assert any(j.authentic_status == "DEGRADED" for j in pushed)
    assert "pushing 1 DEGRADED job(s)" in caplog.text
    assert "withheld" not in caplog.text

    # Both jobs are new and present in the report (DEGRADED included).
    assert result["report"]["new_count"] == 2
    m = json.loads(_manifest_path(tmp_path, result).read_text(encoding="utf-8"))
    assert m["new_count"] == 2
    with open(result["report"]["json"], encoding="utf-8") as fh:
        jobs = json.load(fh)
    statuses = sorted(j["authentic_status"] for j in jobs)
    assert statuses == ["AUTHENTIC", "DEGRADED"]


def test_closed_jobs_still_excluded_from_push(tmp_path, monkeypatch, caplog):
    """The push policy flip only admits DEGRADED jobs; CLOSED jobs remain
    excluded from the telegram push list."""
    caplog.set_level("INFO")
    telegram = mock.MagicMock()
    telegram.configured.return_value = True
    pushed_lists: list[list] = []
    telegram.notify_new.side_effect = lambda jobs: pushed_lists.append(list(jobs)) or len(jobs)
    monkeypatch.setattr("jobharness.runner.telegram", telegram)

    def fake_verify(job, check_reachable=True):
        job.freshness = "fresh"
        if "Senior Backend Engineer" in job.title:
            job.authentic_status = "CLOSED"
        return job

    monkeypatch.setattr("jobharness.runner.verify", fake_verify)

    raws = [
        _raw("Backend Engineer", "Acme", "Remote", "https://acme.com/j/1"),
        _raw("Senior Backend Engineer", "Globex", "Austin, TX", "https://globex.com/j/2"),
    ]
    _run(
        tmp_path, monkeypatch, raws,
        telegram_mock=telegram,
        verify_reachable=True, push_telegram=True,
    )

    # Only the non-CLOSED job reaches the push (if it is genuinely new);
    # CLOSED is never in the pushed list.
    for pushed in pushed_lists:
        assert all(j.authentic_status != "CLOSED" for j in pushed)

