from __future__ import annotations

import csv
import json
from pathlib import Path

from jobharness.models import Job, VALID_AUTHENTIC, CLOSED
from jobharness.report import write_reports


def make_jobs():
    a = Job(title="Backend Engineer", company="Acme", location="Remote")
    a.role = "Backend Engineer"
    a.apply_url_direct = "https://acme.com/j/1"
    a.authentic_status = VALID_AUTHENTIC
    a.genuinely_new = True
    a.freshness = "fresh"
    a.date_posted = "2023-11-14"
    a.seen_sources = ["remoteok"]
    a.tech_stack_keywords = []
    a.compute_hash()
    a.mark_missing()

    b = Job(title="Old Role", company="Gone", location="Remote")
    b.apply_url_direct = "https://gone.com/j/2"
    b.authentic_status = CLOSED
    b.seen_sources = ["indeed"]
    b.compute_hash()
    b.mark_missing()
    return [a, b]


def test_report_writes_three_files(tmp_path):
    jobs = make_jobs()
    res = write_reports(jobs, tmp_path)
    assert Path(res["html"]).exists()
    assert Path(res["csv"]).exists()
    assert Path(res["json"]).exists()
    assert res["total"] == 2
    assert res["closed_count"] == 1
    assert res["new_count"] == 1


def test_report_csv_columns(tmp_path):
    jobs = make_jobs()
    res = write_reports(jobs, tmp_path)
    with open(res["csv"], encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert "title" in header
        assert "apply_url_direct" in header
        assert "authentic_status" in header
        rows = list(reader)
        assert len(rows) == 2


def test_report_json_valid(tmp_path):
    jobs = make_jobs()
    res = write_reports(jobs, tmp_path)
    data = json.loads(Path(res["json"]).read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["authentic_status"] == VALID_AUTHENTIC
