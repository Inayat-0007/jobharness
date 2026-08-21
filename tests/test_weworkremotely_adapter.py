from __future__ import annotations

from unittest import mock

from jobharness.profile import Profile
from jobharness.sources.rss.weworkremotely import WeWorkRemotelyAdapter, _parse_company_title

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <item>
    <title>Acme Corp: Backend Engineer</title>
    <link>https://weworkremotely.com/remote-jobs/1</link>
    <description>Python role, remote.</description>
    <pubDate>Wed, 19 Aug 2026 09:00:00 +0000</pubDate>
  </item>
  <item>
    <title>No Company Role</title>
    <link>https://weworkremotely.com/remote-jobs/2</link>
    <description>Second role.</description>
    <pubDate>Wed, 19 Aug 2026 09:00:00 +0000</pubDate>
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


def test_parse_company_title_splits():
    assert _parse_company_title("Acme Corp: Backend Engineer") == ("Acme Corp", "Backend Engineer")
    assert _parse_company_title("No Company Role") == ("", "No Company Role")


def test_weworkremotely_parses_all_categories():
    with mock.patch("jobharness.sources.rss.weworkremotely.make_client", return_value=FakeCtx()):
        jobs = WeWorkRemotelyAdapter().fetch(Profile(roles=["Backend Engineer"]))
    # Same feed served for every category in WWR_CATEGORIES -> jobs = entries * categories
    cats = {
        "engineering", "fullstack", "front-end", "devops"
    }
    assert len(jobs) == 8
    j = jobs[0]
    assert j.company == "Acme Corp"
    assert j.title == "Backend Engineer"
    assert j.location == "Remote"
    assert j.extra["category"] in cats
    assert j.apply_url == "https://weworkremotely.com/remote-jobs/1"
    # entry without 'Company:' prefix: company empty, whole title kept
    assert any(j2.title == "No Company Role" for j2 in jobs)


def test_weworkremotely_non_200_skips_category():
    class Non200Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            r = FakeResp()
            r.status_code = 503
            return r

    with mock.patch("jobharness.sources.rss.weworkremotely.make_client", return_value=Non200Ctx()):
        assert WeWorkRemotelyAdapter().fetch(Profile(roles=["x"])) == []
