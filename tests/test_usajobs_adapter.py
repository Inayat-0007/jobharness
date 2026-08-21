from __future__ import annotations

import json
from unittest import mock

import pytest

from jobharness.profile import Profile
from jobharness.sources.api.usajobs import USAJobsAdapter


def _fixture(apply_uri):
    return {
        "SearchResult": {
            "SearchResultItems": [
                {
                    "MatchedObjectDescriptor": {
                        "PositionTitle": "Python Backend Engineer",
                        "OrganizationName": "US DOD",
                        "PositionLocationDisplay": "Remote",
                        "QualificationSummary": "Python, Django experience.",
                        "ApplyURI": apply_uri,
                        "PublicationStartDate": "2026-08-01",
                    }
                }
            ]
        }
    }


class FakeResp:
    def __init__(self, data):
        self._data = data
        self.status_code = 200
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
        "jobharness.sources.api.usajobs.secrets.get", lambda k: "fake-key" if k == "USAJOBS_API_KEY" else None
    )
    monkeypatch.setattr("jobharness.sources.api.usajobs.random_delay", lambda: None)
    return USAJobsAdapter()


def _fetch(adapter, data):
    with mock.patch("jobharness.sources.api.usajobs.make_client", return_value=FakeCtx(data)):
        with mock.patch("jobharness.sources.api.usajobs.blocked_response", return_value=False):
            return adapter.fetch(Profile(roles=["Backend Engineer"]))


def test_apply_uri_as_list(adapter):
    jobs = _fetch(adapter, _fixture(["https://www.usajobs.gov/GetJob/ViewDetails/12345"]))
    assert jobs[0].apply_url == "https://www.usajobs.gov/GetJob/ViewDetails/12345"


def test_apply_uri_as_string(adapter):
    """String payload must be taken whole, NOT sliced to its first character."""
    jobs = _fetch(adapter, _fixture("https://www.usajobs.gov/GetJob/ViewDetails/67890"))
    assert jobs[0].apply_url == "https://www.usajobs.gov/GetJob/ViewDetails/67890"


def test_apply_uri_missing(adapter):
    jobs = _fetch(adapter, _fixture(None))
    assert jobs[0].apply_url == ""
    assert jobs[0].source_url == ""


def test_no_api_key_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "jobharness.sources.api.usajobs.secrets.get", lambda k: None
    )
    assert USAJobsAdapter().fetch(Profile(roles=["Backend Engineer"])) == []
