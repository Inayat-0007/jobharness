from __future__ import annotations

import json
from pathlib import Path

from jobharness.dashboard import build_dashboard, collect_reports, compute_stats, description_text
from jobharness.models import Job, VALID_AUTHENTIC, CLOSED
from jobharness.report import write_reports


def _make_runs(tmp_path):
    a = Job(title="Backend Engineer", company="Acme", location="Remote")
    a.role = "Backend Engineer"
    a.apply_url_direct = "https://acme.com/j/1"
    a.authentic_status = VALID_AUTHENTIC
    a.genuinely_new = True
    a.freshness = "fresh"
    a.remote = True
    a.date_posted = "2023-11-14"
    a.description = "<p>Python <b>Django</b> role</p>"
    a.seen_sources = ["remoteok"]
    a.decision = "AUTO_ACCEPT"
    a.match_score = 0.9
    a.compute_hash()

    b = Job(title="Old Role", company="Gone", location="Remote")
    b.apply_url_direct = "https://gone.com/j/2"
    b.authentic_status = CLOSED
    b.seen_sources = ["indeed"]
    b.decision = "REJECT"
    b.compute_hash()

    d1 = tmp_path / "20230101-000000"
    write_reports([a, b], tmp_path, run_ts="20230101-000000")
    assert d1.exists()
    return a, b


def test_collect_reports_dedupes_by_hash(tmp_path):
    a, _ = _make_runs(tmp_path)
    a.authentic_status = CLOSED
    write_reports([a], tmp_path, run_ts="20230102-000000")
    data = collect_reports(tmp_path)
    assert len(data["runs"]) == 2
    assert len(data["jobs"]) == 2
    latest = next(j for j in data["jobs"] if j["title"] == "Backend Engineer")
    assert latest["authentic_status"] == CLOSED


def test_compute_stats(tmp_path):
    _make_runs(tmp_path)
    data = collect_reports(tmp_path)
    stats = compute_stats(data["jobs"])
    assert stats["new_count"] == 1
    assert stats["closed_count"] == 1
    assert stats["remote_count"] == 1
    assert stats["decisions"]["AUTO_ACCEPT"] == 1
    assert stats["sources"]["remoteok"] == 1


def test_build_dashboard(tmp_path):
    _make_runs(tmp_path)
    out = tmp_path / "dashboard.html"
    res = build_dashboard(tmp_path, out)
    assert out.exists()
    assert res["jobs"] == 2
    assert res["runs"] == 1
    html = out.read_text(encoding="utf-8")
    assert "Job Harness Dashboard" in html
    assert "Backend Engineer" in html
    assert "AUTO_ACCEPT" in html


def test_description_text_strips_tags():
    assert description_text("<p>Hello <b>World</b></p>") == "Hello World"
    assert description_text("") == ""
