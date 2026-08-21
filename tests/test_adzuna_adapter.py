from __future__ import annotations

import json
from unittest import mock

import pytest

from jobharness.profile import Profile
from jobharness.sources.api.adzuna import AdzunaAdapter


def _payload(results):
    return {"results": results}


def _result(**kw):
    r = {
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
    monkeypatch.setattr(
        "jobharness.sources.api.adzuna.secrets.get",
        lambda k: {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}.get(k, ""),
    )
    monkeypatch.setattr("jobharness.sources.api.adzuna.random_delay", lambda: None)
    return AdzunaAdapter()


def _fetch(adapter, data, profile=None):
    with mock.patch("jobharness.sources.api.adzuna.make_client", return_value=FakeCtx(data)):
        with mock.patch("jobharness.sources.api.adzuna.blocked_response", return_value=False):
            return adapter.fetch(
                profile or Profile(roles=["Backend Engineer"], adzuna_country="in")
            )


def test_adzuna_extracts_fields(adapter):
    jobs = _fetch(adapter, _payload([_result()]))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Backend Engineer"
    assert j.company == "Acme"
    assert "Bengaluru" in j.location
    assert "India" in j.location  # country name appended
    assert j.apply_url == "https://adzuna.com/land/ad/1"
    assert j.posted_date == "2026-08-20T10:00:00Z"
    assert j.extra["salary"] == 600000
    assert j.extra["contract_time"] == "full_time"


def test_adzuna_remote_keyword_appended(adapter):
    prof = Profile(roles=["Backend Engineer"], remote=True)
    calls = []

    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            calls.append(k)
            return FakeResp(_payload([]))

    with mock.patch("jobharness.sources.api.adzuna.make_client", return_value=Ctx()):
        with mock.patch("jobharness.sources.api.adzuna.blocked_response", return_value=False):
            adapter.fetch(prof)
    assert "remote" in calls[0]["params"]["what"]


def test_adzuna_empty_results(adapter):
    jobs = _fetch(adapter, _payload([]))
    assert jobs == []


def test_adzuna_missing_keys_returns_empty(monkeypatch):
    monkeypatch.setattr("jobharness.sources.api.adzuna.secrets.get", lambda k: "")
    assert AdzunaAdapter().fetch(Profile(roles=["x"])) == []


def test_adzuna_blocked_response_returns_empty(adapter):
    with mock.patch("jobharness.sources.api.adzuna.make_client", return_value=FakeCtx(_payload([]))):
        with mock.patch("jobharness.sources.api.adzuna.blocked_response", return_value=True):
            assert adapter.fetch(Profile(roles=["x"])) == []


def test_adzuna_missing_result_fields_default_empty(adapter):
    jobs = _fetch(adapter, _payload([{"title": ""}]))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == ""
    assert j.location == "India"  # country appended even with empty city
    assert j.apply_url == ""
