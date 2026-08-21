from __future__ import annotations

import json
from unittest import mock

import pytest

from jobharness.profile import Profile
from jobharness.sources.career_page.lever import LeverAdapter


def _posting(**kw):
    p = {
        "id": "abc123",
        "text": "Backend Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc123",
        "categories": {"location": "Bengaluru, India", "commitment": "Full-time"},
        "description": {"plain": "Python API role."},
        "createdAt": "2026-08-19T09:00:00Z",
    }
    p.update(kw)
    return p


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
    monkeypatch.setattr("jobharness.sources.career_page.lever.random_delay", lambda: None)
    return LeverAdapter()


def test_lever_extracts_fields(adapter):
    with mock.patch("jobharness.sources.career_page.lever.make_client", return_value=FakeCtx([_posting()])):
        jobs = adapter.fetch(Profile(roles=["Backend Engineer"], lever_boards=["acme"]))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Backend Engineer"
    assert j.company == "Acme"
    assert j.location == "Bengaluru, India"
    assert j.description == "Python API role."
    assert j.apply_url == "https://jobs.lever.co/acme/abc123"
    assert j.extra["job_id"] == "abc123"
    assert j.extra["commitment"] == "Full-time"


def test_lever_missing_categories_default_remote(adapter):
    with mock.patch("jobharness.sources.career_page.lever.make_client", return_value=FakeCtx([_posting(categories={})])):
        jobs = adapter.fetch(Profile(roles=["Backend Engineer"], lever_boards=["acme"]))
    assert jobs[0].location == "Remote"


def test_lever_skips_non_dict_entries(adapter):
    with mock.patch("jobharness.sources.career_page.lever.make_client", return_value=FakeCtx([_posting(), "garbage", None])):
        jobs = adapter.fetch(Profile(roles=["Backend Engineer"], lever_boards=["acme"]))
    assert len(jobs) == 1


def test_lever_non_200_returns_empty(adapter):
    class Non200:
        status_code = 503

    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return Non200()

    with mock.patch("jobharness.sources.career_page.lever.make_client", return_value=Ctx()):
        assert adapter.fetch(Profile(roles=["x"], lever_boards=["acme"])) == []


def test_lever_empty_list(adapter):
    with mock.patch("jobharness.sources.career_page.lever.make_client", return_value=FakeCtx([])):
        assert adapter.fetch(Profile(roles=["x"], lever_boards=["acme"])) == []
