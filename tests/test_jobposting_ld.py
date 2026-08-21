from __future__ import annotations

from jobharness.sources.jobposting_ld import (
    extract_jobpostings_from_blob,
    extract_jobpostings_from_html,
)

FIXTURE_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "Senior Backend Engineer",
  "description": "We need a senior backend engineer with 5 years experience. Python, API.",
  "datePosted": "2023-11-14",
  "validThrough": "2099-12-31",
  "employmentType": "FULL_TIME",
  "url": "https://acme.com/careers/backend-engineer",
  "hiringOrganization": {"name": "Acme Corp", "sameAs": "https://acme.com"},
  "jobLocation": {"address": {"addressLocality": "New York", "addressRegion": "NY", "addressCountry": "US"}},
  "baseSalary": {"currency": "USD", "value": {"minValue": 120000, "maxValue": 150000}}
}
</script>
</head><body>Apply now.</body></html>
"""


def test_extract_from_html_pulls_all_fields():
    out = extract_jobpostings_from_html(FIXTURE_HTML, "career_page_generic", "https://acme.com/careers", "Fallback")
    assert len(out) == 1
    job = out[0]
    assert job.title == "Senior Backend Engineer"
    assert job.company == "Acme Corp"
    assert job.location == "New York, NY, US"
    assert job.apply_url == "https://acme.com/careers/backend-engineer"
    assert job.posted_date == "2023-11-14"
    assert job.extra["valid_through"] == "2099-12-31"
    assert job.extra["employment_type"] == "FULL_TIME"
    assert "120000-150000" in job.extra["salary"]


def test_extract_from_html_no_invention_for_missing_fields():
    html = '<script type="application/ld+json">{"@type":"JobPosting","title":"Engineer","datePosted":"2023-01-01"}</script>'
    out = extract_jobpostings_from_html(html, "src", "https://x.com", "")
    job = out[0]
    assert job.title == "Engineer"
    # company not in JSON-LD -> empty, never fabricated
    assert job.company == ""
    assert job.extra["valid_through"] == ""


def test_extract_from_blob_handles_list():
    blob = [{"@type": "JobPosting", "title": "A", "url": "https://a.com"}, {"@type": "Thing"}]
    out = extract_jobpostings_from_blob(blob, "src", "https://seed")
    assert len(out) == 1
    assert out[0].title == "A"


def test_extract_from_html_ignores_non_jobposting():
    html = '<script type="application/ld+json">{"@type":"Organization","name":"x"}</script>'
    assert extract_jobpostings_from_html(html, "src", "https://x") == []


def test_extract_graph_nested():
    html = """<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"Nested","url":"https://n.com"}]}</script>"""
    out = extract_jobpostings_from_html(html, "src", "https://x")
    assert len(out) == 1
    assert out[0].title == "Nested"
