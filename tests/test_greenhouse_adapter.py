from __future__ import annotations

import json
from unittest import mock

import pytest

from jobharness.profile import Profile
from jobharness.sources.career_page.greenhouse import GreenhouseAdapter


def _payload(departments=None, jobs=None):
    return {"departments": departments or [], "jobs": jobs or []}


def _job(**kw):
    j = {
        "id": 123,
        "title": "Backend Engineer",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
        "location": {"name": "Bengaluru, India"},
        "offices": [{"name": "Remote"}],
        "content": "<p>Python role</p>",
        "updated_at": "2026-08-19T09:00:00Z",
        "departments": [{"id": 7, "name": "Engineering"}],
    }
    j.update(kw)
    return j


class FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeCtx:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return FakeResp(self._data)


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr("jobharness.sources.career_page.greenhouse.random_delay", lambda: None)
    return GreenhouseAdapter()


def _fetch(adapter, data, profile=None):
    with mock.patch(
        "jobharness.sources.career_page.greenhouse.make_client", return_value=FakeCtx(data)
    ):
        return adapter.fetch(profile or Profile(roles=["Backend Engineer"], greenhouse_boards=["acme"]))


def test_greenhouse_dict_departments(adapter):
    jobs = _fetch(adapter, _payload(jobs=[_job()]))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Backend Engineer"
    assert j.company == "Acme"
    assert j.location == "Bengaluru, India"
    assert j.apply_url == "https://boards.greenhouse.io/acme#123"
    assert j.extra["departments"] == ["Engineering"]
    assert j.extra["job_id"] == 123


def test_greenhouse_list_departments(adapter):
    """departments can be a list of IDs resolved via the top-level map."""
    data = _payload(
        departments=[{"id": 7, "name": "Engineering"}],
        jobs=[_job(departments=[7])],
    )
    jobs = _fetch(adapter, data)
    assert jobs[0].extra["departments"] == ["Engineering"]


def test_greenhouse_string_departments(adapter):
    data = _payload(jobs=[_job(departments=["Platform"])])
    jobs = _fetch(adapter, data)
    assert jobs[0].extra["departments"] == ["Platform"]


def test_greenhouse_location_falls_back_to_offices(adapter):
    data = _payload(jobs=[_job(location={})])
    jobs = _fetch(adapter, data)
    assert jobs[0].location == "Remote"


def test_greenhouse_non_200_skips_board(adapter):
    class Non200:
        def __init__(self):
            self.status_code = 503

    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return Non200()

    with mock.patch(
        "jobharness.sources.career_page.greenhouse.make_client", return_value=Ctx()
    ):
        assert adapter.fetch(Profile(roles=["x"], greenhouse_boards=["acme"])) == []


def test_greenhouse_empty_payload(adapter):
    assert _fetch(adapter, _payload()) == []
