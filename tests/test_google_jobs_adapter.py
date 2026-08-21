from __future__ import annotations

from unittest import mock

import pytest

from jobharness.profile import Profile
from jobharness.sources.exceptions import BlockedError
from jobharness.sources.google_jobs import GoogleJobsAdapter

JOBS_URL = "https://www.google.com/search?q=test&ibp=htl;jobs"

LD_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Backend Engineer","hiringOrganization":{"name":"Acme"},
 "jobLocation":{"address":{"addressLocality":"Remote"}},
 "description":"Python role","datePosted":"2026-08-19",
 "url":"https://acme.com/job/1"}
</script>
</head></html>
"""

BLOB_HTML = '<html><script>window.data = {"@type":"JobPosting","title":"Blob Role","url":"https://acme.com/job/2"}</script></html>'


class FakeResp:
    def __init__(self, html, status=200, blocked=False, url=JOBS_URL):
        self.status_code = status
        self.text = html
        self._blocked = blocked
        self.url = url

    def json(self):
        return {}


class FakeCtx:
    def __init__(self, html, status=200, blocked=False):
        self._html = html
        self._status = status
        self._blocked = blocked

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return FakeResp(self._html, self._status, self._blocked)


def _adapter(html, status=200, blocked=False, monkeypatch=None):
    with mock.patch(
        "jobharness.sources.google_jobs.make_client", return_value=FakeCtx(html, status, blocked)
    ):
        with mock.patch("jobharness.sources.google_jobs.random_delay"):
            return GoogleJobsAdapter()._fetch_once("test+query")


def test_google_jobs_extracts_jsonld():
    jobs = _adapter(LD_HTML)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Backend Engineer"
    assert j.company == "Acme"
    assert j.apply_url == "https://acme.com/job/1"


def test_google_jobs_blob_fallback():
    jobs = _adapter(BLOB_HTML)
    assert len(jobs) == 1


def test_google_jobs_non_200_blocked():
    with pytest.raises(BlockedError):
        _adapter("", status=403)


def test_google_jobs_blocked():
    # 403 triggers blocked_response -> BlockedError, even with valid HTML
    with pytest.raises(BlockedError):
        _adapter(LD_HTML, status=403)


def test_google_jobs_is_shell():
    adapter = GoogleJobsAdapter()
    shell_url = "https://www.google.com/search?q=test&udm=8"
    # redirect off the jobs vertical (udm=8 shell)
    assert adapter._is_shell(FakeResp("<html>normal</html>", url=shell_url))
    # JS-only / anti-bot markers in the body
    assert adapter._is_shell(FakeResp("<html>Please enable javascript</html>"))
    assert adapter._is_shell(FakeResp("<html>we detected unusual traffic</html>"))
    assert adapter._is_shell(FakeResp('<html><noscript>enable js</noscript></html>'))
    # clean jobs page is not a shell
    assert not adapter._is_shell(FakeResp("<html>no jobs</html>"))


def test_google_jobs_clean_page_empty():
    assert _adapter("<html><body>no jobs</body></html>") == []


def test_google_jobs_query_encoding():
    """Query terms must be URL-encoded in the google search URL."""
    prof = Profile(roles=["Backend Engineer"], keywords=["python api"], remote=True)
    adapter = GoogleJobsAdapter()

    class Ctx:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **k):
            self.calls.append(url)
            r = FakeResp("<html></html>")
            r.status_code = 200
            return r

    ctx = Ctx()
    with mock.patch("jobharness.sources.google_jobs.make_client", return_value=ctx):
        with mock.patch("jobharness.sources.google_jobs.random_delay"):
            with mock.patch("jobharness.sources.google_jobs.time.sleep"):
                adapter.fetch(prof)
    # spaces in keyword lists must be encoded, not raw in the query URL
    assert " " not in ctx.calls[0]
    assert "python+api" in ctx.calls[0]
