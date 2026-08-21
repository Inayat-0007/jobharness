from __future__ import annotations

from unittest import mock

import pytest

from jobharness.profile import Profile
from jobharness.sources.rss.jobicy import JobicyAdapter

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <item>
    <title>Senior Python Engineer</title>
    <link>https://jobicy.com/job/1</link>
    <description>Python backend role at Acme.&lt;br/&gt;Remote.</description>
    <pubDate>Thu, 20 Aug 2026 10:00:00 +0000</pubDate>
    <author>acme@example.com (Acme Corp)</author>
  </item>
</channel>
</rss>"""


class FakeResp:
    status_code = 200
    content = FEED


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


class Non200Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return Non200Resp()


def test_jobicy_parses_feed():
    with mock.patch("jobharness.sources.rss.jobicy.make_client", return_value=FakeCtx()):
        jobs = JobicyAdapter().fetch(Profile(roles=["Backend Engineer"]))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Senior Python Engineer"
    assert j.company == "acme@example.com (Acme Corp)"
    assert j.location == "Remote"
    assert "Python backend role" in j.description
    assert j.apply_url == "https://jobicy.com/job/1"
    assert j.posted_date == "Thu, 20 Aug 2026 10:00:00 +0000"


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
            r.content = b"<rss><channel></channel></rss>"
            return r

    with mock.patch("jobharness.sources.rss.jobicy.make_client", return_value=EmptyCtx()):
        assert JobicyAdapter().fetch(Profile(roles=["x"])) == []
