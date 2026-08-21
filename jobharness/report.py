from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

from jinja2 import Environment, select_autoescape

from .models import Job

_env = Environment(autoescape=select_autoescape(["html", "xml"]))
_env.trim_blocks = True

REPORT_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Job Harness Report - {{ run_ts }}</title>
<style>
body{font-family:system-ui,sans-serif;margin:24px;color:#222}
h1{font-size:1.4rem}
table{border-collapse:collapse;width:100%;font-size:0.85rem;table-layout:fixed}
th,td{border:1px solid #ddd;padding:8px;vertical-align:top;word-wrap:break-word}
th{background:#f4f4f4;text-align:left}
tr.closed{background:#fff0f0}
tr.new{font-weight:bold}
a.btn{display:inline-block;padding:4px 10px;background:#1a73e8;color:#fff;text-decoration:none;border-radius:4px}
.bad{color:#b00}.ok{color:#080}
</style></head><body>
<h1>Job Harness Report - {{ run_ts }}</h1>
<p>{{ jobs|length }} jobs. {{ new_count }} genuinely new. {{ closed_count }} closed.</p>
<table><thead><tr>
<th>Fresh</th><th>Date</th><th>Title</th><th>Company</th><th>Loc</th><th>Exp</th><th>Salary</th><th>Score</th><th>Decision</th><th>Apply</th><th>Status</th><th>Domain</th><th>Sources</th>
</tr></thead><tbody>
{% for j in jobs %}
<tr class="{% if j.authentic_status=='CLOSED' %}closed{% elif j.genuinely_new %}new{% endif %}">
<td>{{ j.freshness }}</td>
<td>{{ j.date_posted }}</td>
<td>{{ j.title }}<br><small>{{ j.role }}</small></td>
<td>{{ j.company }}</td>
<td>{{ j.location }}{% if j.remote %} (remote){% endif %}</td>
<td>{{ j.experience_needed }}</td>
<td>{{ j.salary_if_present }}</td>
<td>{{ j.confidence_score }}</td>
<td>{{ j.decision or '' }}{% if j.reason %}<br><small>{{ j.reason[0] }}</small>{% endif %}</td>
<td><a class="btn" href="{{ j.apply_url_direct }}" target="_blank">Apply</a></td>
<td class="{% if j.authentic_status=='CLOSED' %}bad{% else %}ok{% endif %}">{{ j.authentic_status }}</td>
<td><small>{{ j.employer_domain }}</small></td>
<td>{{ j.seen_sources|join(', ') }}</td>
</tr>
{% endfor %}
</tbody></table></body></html>"""


def write_reports(jobs: list[Job], out_dir: str | Path, run_ts: str | None = None) -> dict[str, str]:
    ts = run_ts or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = Path(out_dir) / ts
    d.mkdir(parents=True, exist_ok=True)

    auth = [j for j in jobs if j.authentic_status != "CLOSED"]
    new_count = sum(1 for j in jobs if j.genuinely_new and j.authentic_status != "CLOSED")
    closed_count = sum(1 for j in jobs if j.authentic_status == "CLOSED")

    json_path = d / "report.json"
    json_path.write_text(
        json.dumps([j.to_dict() for j in jobs], indent=2, default=str), encoding="utf-8"
    )

    csv_path = d / "report.csv"
    fields = [
        "freshness", "date_posted", "title", "role", "company", "location", "remote",
        "experience_needed", "salary_if_present", "seniority", "tech_stack_keywords",
        "confidence_score", "authentic_status", "employer_domain", "valid_through",
        "apply_url_direct", "source_name", "source_url", "first_seen_at",
        "genuinely_new", "seen_sources", "missing_fields", "job_id_hash",
        "decision", "identity_score", "authenticity_score", "match_score",
        "matched_via", "possible_duplicate_of", "canonical_job_id", "block_key",
        "evidence", "negative_evidence", "reason",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for j in jobs:
            d_ = j.to_dict()
            w.writerow([", ".join(map(str, d_[k])) if isinstance(d_[k], list) else d_[k] for k in fields])

    html_path = d / "report.html"
    html_path.write_text(
        _env.from_string(REPORT_HTML).render(
            jobs=jobs, run_ts=ts, new_count=new_count, closed_count=closed_count
        ),
        encoding="utf-8",
    )

    return {
        "dir": str(d),
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "pdf": "",
        "new_count": new_count,
        "closed_count": closed_count,
        "total": len(jobs),
        "authentic": len(auth),
    }


def write_pdf(html_path: str, pdf_path: str | Path) -> str:
    """Print the HTML report to a structured PDF via headless Chromium.

    Returns the PDF path on success, or '' (with a logged warning) if
    Playwright is unavailable or the conversion fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("[report] PDF disabled: playwright not available")
        return ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "8mm", "right": "8mm"},
            )
            browser.close()
        return str(pdf_path)
    except Exception as e:
        print(f"[report] PDF generation failed: {e}")
        return ""


def write_pdf(html_path: str, pdf_path: str | Path) -> str:
    """Print the HTML report to a structured PDF via headless Chromium.

    Returns the PDF path on success, or '' (with a logged warning) if
    Playwright is unavailable or the conversion fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("[report] PDF disabled: playwright not available")
        return ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "8mm", "right": "8mm"},
            )
            browser.close()
        return str(pdf_path)
    except Exception as e:
        print(f"[report] PDF generation failed: {e}")
        return ""
