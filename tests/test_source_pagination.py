from __future__ import annotations

import json
from unittest import mock

import pytest

from jobharness.models import RawJob
from jobharness.profile import Profile
from jobharness.sources.api.adzuna import AdzunaAdapter
from jobharness.sources.api.usajobs import USAJobsAdapter
from jobharness.sources.career_page.browser_generic import CareerPageBrowserAdapter
from jobharness.sources.career_page.greenhouse import GreenhouseAdapter
from jobharness.sources.linkedin_guest import LinkedInGuestAdapter


class FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = json.dumps(data)

    def json(self):
        return self._data


def _az_result(**kw):
    r = {
        "id": "ad-1",
        "title": "Backend Engineer",
        "company": {"displayname": "Acme"},
        "location": {"displayname": "Bengaluru"},
        "description": "Python API backend.",
        "redirect_url": "https://adzuna.com/land/ad/1",
        "url": "https://adzuna.com/ad/1",
        "created": "2026-08-20T10:00:00Z",
        "salary_min": 600000,
        "contract_time": "full_time",
    }
    r.update(kw)
    return r


def _az_payload(results):
    return {"results": results}


@pytest.fixture
def adzuna(monkeypatch):
    monkeypatch.setattr(
        "jobharness.sources.api.adzuna.secrets.get",
        lambda k: {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}.get(k, ""),
    )
    monkeypatch.setattr("jobharness.sources.api.adzuna.random_delay", lambda: None)
    return AdzunaAdapter()


class PageAwareCtx:
    """Returns a per-page payload based on the trailing page number in the URL."""

    def __init__(self, page_data, urls):
        self._page_data = page_data
        self._urls = urls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        url = a[0] if a else k.get("url", "")
        self._urls.append(url)
        page = 1
        marker = "/search/"
        if marker in url:
            page = int(url.rsplit(marker, 1)[1])
        return FakeResp(self._page_data.get(page, _az_payload([])))


def test_adzuna_max_pages_2_requests_page_2_and_returns_union(adzuna):
    page_data = {
        1: _az_payload([_az_result(id="ad-1", title="Job One"), _az_result(id="ad-2", title="Job Two")]),
        2: _az_payload([_az_result(id="ad-2", title="Job Two"), _az_result(id="ad-3", title="Job Three")]),
    }
    urls = []
    with mock.patch("jobharness.sources.api.adzuna.make_client", return_value=PageAwareCtx(page_data, urls)):
        with mock.patch("jobharness.sources.api.adzuna.blocked_response", return_value=False):
            jobs = adzuna.fetch(Profile(roles=["Backend Engineer"], adzuna_country="in", max_pages=2))
    assert [u.rsplit("/search/", 1)[1] for u in urls] == ["1", "2"]
    assert [j.title for j in jobs] == ["Job One", "Job Two", "Job Three"]  # ad-2 deduped
    assert len(jobs) == 3


def test_adzuna_max_pages_1_requests_only_page_1(adzuna):
    urls = []
    with mock.patch(
        "jobharness.sources.api.adzuna.make_client",
        return_value=PageAwareCtx({1: _az_payload([_az_result()])}, urls),
    ):
        with mock.patch("jobharness.sources.api.adzuna.blocked_response", return_value=False):
            jobs = adzuna.fetch(Profile(roles=["Backend Engineer"], adzuna_country="in", max_pages=1))
    assert len(urls) == 1
    assert urls[0].endswith("/search/1")
    assert len(jobs) == 1


def test_adzuna_stops_early_when_page_returns_no_results(adzuna):
    urls = []
    with mock.patch(
        "jobharness.sources.api.adzuna.make_client",
        return_value=PageAwareCtx({1: _az_payload([])}, urls),
    ):
        with mock.patch("jobharness.sources.api.adzuna.blocked_response", return_value=False):
            jobs = adzuna.fetch(Profile(roles=["Backend Engineer"], adzuna_country="in", max_pages=5))
    assert len(urls) == 1
    assert jobs == []


@pytest.fixture
def greenhouse(monkeypatch):
    monkeypatch.setattr("jobharness.sources.career_page.greenhouse.random_delay", lambda: None)
    return GreenhouseAdapter()


def test_greenhouse_parallel_preserves_board_order(greenhouse):
    boards = ["aaa", "bbb", "ccc", "ddd"]

    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            url = a[0] if a else ""
            board = url.split("/boards/")[1].split("/")[0]
            data = {
                "jobs": [
                    {
                        "id": 1,
                        "title": f"{board} job",
                        "absolute_url": f"https://x/{board}",
                        "location": {"name": "Remote"},
                        "departments": [],
                    }
                ]
            }
            return FakeResp(data)

    with mock.patch("jobharness.sources.career_page.greenhouse.make_client", return_value=Ctx()):
        jobs = greenhouse.fetch(
            Profile(roles=["x"], greenhouse_boards=boards, career_fetch_workers=4)
        )
    assert [j.title for j in jobs] == [f"{b} job" for b in boards]


def test_linkedin_enrich_cap_limits_enrichment(monkeypatch):
    adapter = LinkedInGuestAdapter()
    jobs = [
        RawJob(
            source_name="linkedin_guest",
            source_url=f"https://x/{i}",
            title=f"Job {i}",
            company="",
            location="",
            description="",
            apply_url=f"https://x/{i}",
        )
        for i in range(12)
    ]
    gets = {"n": 0}

    class BoomClient:
        def get(self, *a, **k):
            gets["n"] += 1
            raise RuntimeError("no network")

    monkeypatch.setattr("jobharness.sources.linkedin_guest.get_shared_client", lambda **k: BoomClient())
    monkeypatch.setattr("jobharness.sources.linkedin_guest.random_delay", lambda: None)
    monkeypatch.setattr(LinkedInGuestAdapter, "_warm_up_cookies", lambda self: None)
    adapter._enrich(jobs, cap=5)
    assert gets["n"] == 5


def test_linkedin_fetch_passes_profile_enrich_cap(monkeypatch):
    calls = []

    def fake_enrich(self, jobs, cap):
        calls.append((len(jobs), cap))

    monkeypatch.setattr(LinkedInGuestAdapter, "_enrich", fake_enrich)
    monkeypatch.setattr("jobharness.sources.linkedin_guest.random_delay", lambda: None)
    html = """
<li>
  <a class="base-card__full-link" href="https://x/1">
  <h3 class="base-search-card__title">Engineer</h3>
  <a class="hidden-nested-link">Acme</a>
  <span class="job-search-card__location">India</span>
  <time datetime="2026-08-20"></time>
</li>
"""

    class Resp:
        status_code = 200
        text = html

    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr("jobharness.sources.linkedin_guest.make_client", lambda **k: Ctx())
    jobs = LinkedInGuestAdapter().fetch(Profile(roles=["Backend Engineer"], enrich_cap=7))
    assert len(calls) == 1
    assert calls[0][0] == len(jobs) == 10  # 10 pages x 1 card, under the 50 hard cap
    assert calls[0][1] == 7


def test_browser_generic_uses_profile_workers_and_enrich_cap(monkeypatch):
    seeds = [{"url": f"https://careers.example.com/{i}", "company": f"Co{i}"} for i in range(6)]
    seen = []

    def fake_visit(self, worker, chunk, enrich_cap):
        seen.append((worker, [s[1] for s in chunk], enrich_cap))
        return (
            [
                RawJob(
                    source_name="career_page_browser",
                    source_url=f"https://x/{worker}/{i}",
                    title=f"Job {worker}-{i}",
                    company="",
                    location="",
                    apply_url="",
                )
                for i in range(2)
            ],
            0,
        )

    monkeypatch.setattr(CareerPageBrowserAdapter, "_visit_chunk", fake_visit)
    jobs = CareerPageBrowserAdapter().fetch(
        Profile(career_pages=seeds, browser_career_workers=3, enrich_cap=11)
    )
    assert len(seen) == 3  # chunks derived from profile.browser_career_workers, not a fixed 4
    assert [w for w, _, _ in seen] == [0, 1, 2]
    assert all(cap == 11 for _, _, cap in seen)
    assert len(jobs) == 6


def test_usajobs_max_pages_2_requests_page_2(monkeypatch):
    monkeypatch.setattr(
        "jobharness.sources.api.usajobs.secrets.get",
        lambda k: "fake-key" if k == "USAJOBS_API_KEY" else None,
    )
    monkeypatch.setattr("jobharness.sources.api.usajobs.random_delay", lambda: None)
    calls = []

    def _fixture(title):
        return {
            "SearchResult": {
                "SearchResultItems": [
                    {
                        "MatchedObjectDescriptor": {
                            "PositionTitle": title,
                            "OrganizationName": "",
                            "PositionLocationDisplay": "",
                            "QualificationSummary": "",
                            "ApplyURI": "",
                            "PublicationStartDate": "",
                        }
                    }
                ]
            }
        }

    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            params = k.get("params", {})
            calls.append(params)
            return FakeResp(_fixture(f"Job p{params.get('Page', 1)}"))

    with mock.patch("jobharness.sources.api.usajobs.make_client", return_value=Ctx()):
        with mock.patch("jobharness.sources.api.usajobs.blocked_response", return_value=False):
            jobs = USAJobsAdapter().fetch(Profile(roles=["Backend Engineer"], max_pages=2))
    assert [p.get("Page") for p in calls] == [1, 2]
    assert [j.title for j in jobs] == ["Job p1", "Job p2"]


def test_usajobs_max_pages_1_requests_only_page_1(monkeypatch):
    monkeypatch.setattr(
        "jobharness.sources.api.usajobs.secrets.get",
        lambda k: "fake-key" if k == "USAJOBS_API_KEY" else None,
    )
    monkeypatch.setattr("jobharness.sources.api.usajobs.random_delay", lambda: None)
    calls = []

    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            params = k.get("params", {})
            calls.append(params)
            return FakeResp(
                {
                    "SearchResult": {
                        "SearchResultItems": [
                            {
                                "MatchedObjectDescriptor": {
                                    "PositionTitle": "T",
                                    "OrganizationName": "",
                                    "PositionLocationDisplay": "",
                                    "QualificationSummary": "",
                                    "ApplyURI": "",
                                    "PublicationStartDate": "",
                                }
                            }
                        ]
                    }
                }
            )

    with mock.patch("jobharness.sources.api.usajobs.make_client", return_value=Ctx()):
        with mock.patch("jobharness.sources.api.usajobs.blocked_response", return_value=False):
            USAJobsAdapter().fetch(Profile(roles=["Backend Engineer"], max_pages=1))
    assert len(calls) == 1
    assert calls[0].get("Page") == 1
