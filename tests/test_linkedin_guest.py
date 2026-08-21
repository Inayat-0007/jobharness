from __future__ import annotations

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
