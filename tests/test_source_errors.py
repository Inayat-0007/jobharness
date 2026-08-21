from __future__ import annotations

import unittest.mock
from contextlib import contextmanager

import pytest

from jobharness.models import RawJob
from jobharness.profile import Profile
from jobharness.sources.career_page.browser_generic import CareerPageBrowserAdapter
from jobharness.sources.exceptions import BlockedError, SourceDownError
from jobharness.sources.internshala import InternshalaAdapter
from jobharness.sources.linkedin import LinkedInAdapter
from jobharness.sources.naukri import NaukriAdapter


class _FakePage:
    def __init__(self, url="https://example.com/jobs", goto_error=None):
        self._url = url
        self._goto_error = goto_error

    @property
    def url(self):
        return self._url

    def goto(self, url, **kw):
        if self._goto_error is not None:
            raise self._goto_error

    def content(self):
        return "<html><body>jobs</body></html>"

    def query_selector(self, sel):
        return None

    def query_selector_all(self, sel):
        return []

    def evaluate(self, js):
        return []


class _FakeBrowser:
    def __init__(self, page):
        self.pages = [page]

    def new_page(self):
        return self.pages[0]


class _FakeHTTPResponse:
    status_code = 200
    text = "<html><body>jobs</body></html>"


class _FakeHTTPClient:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kw):
        return _FakeHTTPResponse()


@contextmanager
def _fake_open_browser(page):
    yield object(), _FakeBrowser(page)


def _no_sleep(monkeypatch, mod):
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)


def test_naukri_blocked_propagates_after_mobile_retry(monkeypatch):
    from jobharness.sources import naukri as naukri_mod

    page = _FakePage()
    monkeypatch.setattr(naukri_mod, "open_browser", lambda *a, **k: _fake_open_browser(page))
    monkeypatch.setattr(naukri_mod, "wait_for_login", lambda *a, **k: False)
    monkeypatch.setattr(naukri_mod, "wait_for_captcha", lambda *a, **k: False)
    block = unittest.mock.Mock(return_value="denied")
    monkeypatch.setattr(naukri_mod, "detect_block", block)
    _no_sleep(monkeypatch, naukri_mod)

    with pytest.raises(BlockedError):
        NaukriAdapter().fetch(Profile(roles=["Backend Engineer"]))
    assert block.call_count == 2


def test_internshala_captcha_wall_raises_blocked(monkeypatch):
    from jobharness.sources import internshala as internshala_mod

    page = _FakePage()
    monkeypatch.setattr(internshala_mod, "open_browser", lambda *a, **k: _fake_open_browser(page))
    monkeypatch.setattr(internshala_mod, "wait_for_captcha", lambda *a, **k: False)
    block = unittest.mock.Mock(return_value="captcha")
    monkeypatch.setattr(internshala_mod, "detect_block", block)
    _no_sleep(monkeypatch, internshala_mod)

    with pytest.raises(BlockedError):
        InternshalaAdapter().fetch(Profile(roles=["Backend Engineer"]))
    assert block.call_count == 2


def test_linkedin_goto_timeout_raises_source_down(monkeypatch):
    from jobharness.sources import linkedin as linkedin_mod

    page = _FakePage(goto_error=TimeoutError("navigation timeout"))
    monkeypatch.setattr(linkedin_mod, "open_browser", lambda *a, **k: _fake_open_browser(page))
    monkeypatch.setattr(linkedin_mod, "detect_block", lambda p: "")
    monkeypatch.setattr(linkedin_mod, "wait_for_login", lambda *a, **k: False)
    monkeypatch.setattr(linkedin_mod, "wait_for_captcha", lambda *a, **k: False)
    monkeypatch.setattr(linkedin_mod, "wait_for_selector_any", lambda *a, **k: "")
    monkeypatch.setattr(linkedin_mod, "scroll_to_load", lambda *a, **k: None)
    _no_sleep(monkeypatch, linkedin_mod)

    with pytest.raises(SourceDownError):
        LinkedInAdapter().fetch(Profile(roles=["Backend Engineer"]))


def test_internshala_launch_failure_propagates_untyped(monkeypatch):
    from jobharness.sources import internshala as internshala_mod

    def boom(*a, **k):
        raise RuntimeError("context launch failed")

    monkeypatch.setattr(internshala_mod, "open_browser", boom)
    _no_sleep(monkeypatch, internshala_mod)

    with pytest.raises(RuntimeError, match="context launch failed"):
        InternshalaAdapter().fetch(Profile(roles=["Backend Engineer"]))


def test_naukri_clean_empty_still_returns_empty(monkeypatch):
    from jobharness.sources import naukri as naukri_mod

    page = _FakePage()
    monkeypatch.setattr(naukri_mod, "open_browser", lambda *a, **k: _fake_open_browser(page))
    monkeypatch.setattr(naukri_mod, "detect_block", lambda p: "")
    monkeypatch.setattr(naukri_mod, "wait_for_selector_any", lambda *a, **k: "")
    monkeypatch.setattr(naukri_mod, "scroll_to_load", lambda *a, **k: None)
    _no_sleep(monkeypatch, naukri_mod)

    assert NaukriAdapter().fetch(Profile(roles=["Backend Engineer"])) == []


def test_career_browser_all_chunks_fail_raises_source_down(monkeypatch):
    from jobharness.sources.career_page import browser_generic as bg

    prof = Profile(career_pages=[{"url": "https://a.example/careers", "company": "A"}])
    monkeypatch.setattr(
        bg, "open_browser", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("browser launch failed"))
    )
    monkeypatch.setattr(bg, "make_client", lambda *a, **k: _FakeHTTPClient())
    monkeypatch.setattr(bg, "extract_jobpostings_from_html", lambda *a, **k: [])
    with pytest.raises(SourceDownError, match="all 1 chunk"):
        CareerPageBrowserAdapter().fetch(prof)


def test_career_browser_browser_fail_http_fallback_returns_jobs(monkeypatch):
    from jobharness.sources.career_page import browser_generic as bg

    jobs = [
        RawJob(
            source_name="career_page_browser",
            source_url="https://a.example/jobs/1",
            title="Engineer at A",
        )
    ]
    prof = Profile(career_pages=[{"url": "https://a.example/careers", "company": "A"}])
    monkeypatch.setattr(
        bg, "open_browser", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("browser launch failed"))
    )
    monkeypatch.setattr(bg, "make_client", lambda *a, **k: _FakeHTTPClient())
    monkeypatch.setattr(bg, "extract_jobpostings_from_html", lambda *a, **k: jobs)
    assert CareerPageBrowserAdapter().fetch(prof) == jobs


def test_career_browser_rendered_empty_returns_empty(monkeypatch):
    prof = Profile(career_pages=[{"url": "https://a.example/careers", "company": "A"}])

    monkeypatch.setattr(
        CareerPageBrowserAdapter,
        "_visit_chunk",
        staticmethod(lambda worker, chunk, enrich_cap: ([], 0)),
    )
    assert CareerPageBrowserAdapter().fetch(prof) == []


def test_career_browser_all_seeds_nav_fail_raises_source_down(monkeypatch):
    prof = Profile(career_pages=[{"url": "https://a.example/careers", "company": "A"}])

    monkeypatch.setattr(
        CareerPageBrowserAdapter,
        "_visit_chunk",
        staticmethod(lambda worker, chunk, enrich_cap: ([], len(chunk))),
    )
    with pytest.raises(SourceDownError, match="failed to navigate"):
        CareerPageBrowserAdapter().fetch(prof)


def test_career_browser_partial_chunk_failure_is_best_effort(monkeypatch):
    prof = Profile(
        career_pages=[
            {"url": "https://a.example/careers", "company": "A"},
            {"url": "https://b.example/careers", "company": "B"},
        ]
    )
    jobs = [RawJob(source_name="career_page_browser", source_url="https://a.example/jobs/1", title="Engineer at A")]

    def fake_chunk(worker, chunk, enrich_cap):
        if worker == 0:
            return jobs, 0
        raise SourceDownError("chunk down")

    monkeypatch.setattr(CareerPageBrowserAdapter, "_visit_chunk", staticmethod(fake_chunk))
    assert CareerPageBrowserAdapter().fetch(prof) == jobs
