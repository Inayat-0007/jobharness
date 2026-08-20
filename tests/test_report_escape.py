from __future__ import annotations

import html as _html

from jobharness.models import Job, VALID_AUTHENTIC
from jobharness.report import write_reports

_RAW = "<script>alert(1)</script>"
_ESCAPED = _html.escape(_RAW)


def _job_xss():
    j = Job(title=_RAW, company="Acme", location="Remote")
    j.apply_url_direct = "https://acme.com/j/1"
    j.authentic_status = VALID_AUTHENTIC
    j.freshness = "fresh"
    j.date_posted = "2023-11-14"
    j.seen_sources = ["remoteok"]
    j.tech_stack_keywords = []
    j.confidence_score = 60
    j.compute_hash()
    j.mark_missing()
    return j


def test_report_html_escapes_dangerous_title(tmp_path):
    res = write_reports([_job_xss()], tmp_path)
    body = open(res["html"], encoding="utf-8").read()
    # raw markup must NOT be present (no XSS); HTML-escaped form must be present.
    assert _RAW not in body
    assert _ESCAPED in body


def test_report_still_has_apply_link(tmp_path):
    res = write_reports([_job_xss()], tmp_path)
    body = open(res["html"], encoding="utf-8").read()
    assert 'href="https://acme.com/j/1"' in body
