from __future__ import annotations

import json
from unittest import mock

import pytest

from jobharness.profile import Profile
from jobharness.sources.exceptions import ParseFailureError
from jobharness.sources.rss.jobicy import JobicyAdapter

FEED = json.dumps(
    {
        "success": True,
        "jobCount": 1,
        "jobs": [
            {
                "id": 1,
                "url": "https://jobicy.com/jobs/1-senior-python-engineer",
                "jobTitle": "Senior Python Engineer",
                "companyName": "Acme Corp",
                "jobGeo": "USA",
                "jobExcerpt": "Python backend role at Acme. Remote.",
                "pubDate": "2026-08-20T10:00:00+00:00",
            }
        ],
    }
).encode()


class FakeResp:
    status_code = 200
    content = FEED

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class FakeCtx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return FakeResp()


class Non200Resp:
    status_code = 503
    content = b""
    text = ""


class Non200Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return Non200Resp()


def test_jobicy_parses_api_payload():
    with mock.patch("jobharness.sources.rss.jobicy.make_client", return_value=FakeCtx()):
        jobs = JobicyAdapter().fetch(Profile(roles=["Backend Engineer"]))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Senior Python Engineer"
    assert j.company == "Acme Corp"
    assert j.location == "USA"
    assert "Python backend role" in j.description
    assert j.apply_url == "https://jobicy.com/jobs/1-senior-python-engineer"
    assert j.posted_date == "2026-08-20T10:00:00+00:00"
    assert j.extra["salary_min"] == ""


def test_jobicy_non_200_returns_empty():
    with mock.patch("jobharness.sources.rss.jobicy.make_client", return_value=Non200Ctx()):
        assert JobicyAdapter().fetch(Profile(roles=["x"])) == []


def test_jobicy_empty_feed():
    class EmptyCtx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            r = FakeResp()
            r.content = b'{"success": true, "jobs": []}'
            return r

    with mock.patch("jobharness.sources.rss.jobicy.make_client", return_value=EmptyCtx()):
        assert JobicyAdapter().fetch(Profile(roles=["x"])) == []


def test_jobicy_missing_jobs_list_raises_parse_failure():
    class BadCtx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            r = FakeResp()
            r.content = b'{"success": true}'
            return r

    with mock.patch("jobharness.sources.rss.jobicy.make_client", return_value=BadCtx()):
        with pytest.raises(ParseFailureError):
            JobicyAdapter().fetch(Profile(roles=["x"]))


def test_jobicy_non_dict_payload_raises_parse_failure():
    class BadCtx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            r = FakeResp()
            r.content = b"[1, 2, 3]"
            return r

    with mock.patch("jobharness.sources.rss.jobicy.make_client", return_value=BadCtx()):
        with pytest.raises(ParseFailureError):
            JobicyAdapter().fetch(Profile(roles=["x"]))
