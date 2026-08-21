from __future__ import annotations

import threading
from unittest.mock import Mock, patch

from jobharness.models import RawJob
from jobharness.sources.linkedin_guest import LinkedInGuestAdapter

_SAMPLE = """
<html><body>
<div class="results">
<li>
  <div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:123">
    <a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/software-engineer-123?position=1&amp;refId=abc">
      <span class="sr-only">Software Engineer - Fresher</span>
    </a>
    <h3 class="base-search-card__title">Software Engineer - Fresher</h3>
    <h4 class="base-search-card__subtitle">
      <a class="hidden-nested-link" href="https://in.linkedin.com/company/acme">Acme Tech</a>
    </h4>
    <div class="base-search-card__metadata">
      <span class="job-search-card__location">Bengaluru, Karnataka, India</span>
      <time class="job-search-card__listdate--new" datetime="2026-08-20">20 hours ago</time>
    </div>
  </div>
</li>
<li>
  <div class="base-card base-search-card job-search-card">
    <a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/associate-engineer-456">
      <span class="sr-only">Associate Software Engineer</span>
    </a>
    <h3 class="base-search-card__title">Associate Software Engineer</h3>
    <h4 class="base-search-card__subtitle">
      <a class="hidden-nested-link" href="https://in.linkedin.com/company/globex">Globex</a>
    </h4>
    <div class="base-search-card__metadata">
      <span class="job-search-card__location">Hyderabad, Telangana, India</span>
      <time class="job-search-card__listdate--new" datetime="2026-08-21">1 hour ago</time>
    </div>
  </div>
</li>
</div>
</body></html>
"""


def test_parse_guest_cards():
    jobs = LinkedInGuestAdapter()._parse(_SAMPLE, "India")
    assert len(jobs) == 2
    j = jobs[0]
    assert j.title == "Software Engineer - Fresher"
    assert j.company == "Acme Tech"
    assert j.location == "Bengaluru, Karnataka, India"
    assert j.posted_date == "2026-08-20"
    assert j.apply_url == "https://in.linkedin.com/jobs/view/software-engineer-123?position=1&refId=abc"
    assert jobs[1].title == "Associate Software Engineer"
    assert jobs[1].posted_date == "2026-08-21"


def test_parse_empty_html():
    assert LinkedInGuestAdapter()._parse("<html></html>", "India") == []


class _FakeClient:
    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def get(self, url, headers=None, **kwargs):
        with self._lock:
            self.calls.append(url)
        resp = Mock()
        if url == "https://www.linkedin.com/jobs/":
            resp.status_code = 200
            resp.text = "<html></html>"
        else:
            resp.status_code = self.status
            resp.text = '<div class="show-more-less-html__markup"><p>Hello world</p></div>'
        return resp


def _job(url: str) -> RawJob:
    return RawJob(
        source_name="linkedin_guest",
        source_url=url,
        title="Software Engineer - Fresher",
        company="Acme Tech",
        location="India",
        description="",
        posted_date="",
        apply_url=url,
    )


@patch("jobharness.sources.linkedin_guest.random_delay", return_value=None)
@patch("jobharness.sources.linkedin_guest.get_shared_client")
def test_enrich_uses_shared_client_and_warm_up(mock_shared, _mock_delay):
    client = _FakeClient()
    mock_shared.return_value = client
    job = _job("https://www.linkedin.com/jobs/view/software-engineer-123?position=1&refId=abc")
    LinkedInGuestAdapter()._enrich([job], cap=10)

    assert all(call.kwargs.get("timeout") == 20.0 for call in mock_shared.call_args_list)
    assert "https://www.linkedin.com/jobs/" in client.calls
    assert "https://www.linkedin.com/jobs/view/software-engineer-123" in client.calls
    assert "Hello world" in job.description


@patch("jobharness.sources.linkedin_guest.time.sleep", return_value=None)
@patch("jobharness.sources.linkedin_guest.random_delay", return_value=None)
@patch("jobharness.sources.linkedin_guest.get_shared_client")
def test_enrich_circuit_breaker_stops_on_consecutive_999(mock_shared, _mock_delay, _mock_sleep):
    client = _FakeClient(status=999)
    mock_shared.return_value = client
    jobs = [_job(f"https://www.linkedin.com/jobs/view/job-{i}") for i in range(10)]
    LinkedInGuestAdapter()._enrich(jobs, cap=10)

    detail_calls = [u for u in client.calls if u != "https://www.linkedin.com/jobs/"]
    assert len(detail_calls) >= 3
    assert len(detail_calls) < 10
    assert all(j.description == "" for j in jobs)
