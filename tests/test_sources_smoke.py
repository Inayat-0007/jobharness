from __future__ import annotations

from unittest import mock

import pytest

from jobharness.browser import detect_block
from jobharness.sources.internshala import InternshalaAdapter
from jobharness.sources.naukri import NaukriAdapter
from jobharness.sources.hirist import HiristAdapter
from jobharness.sources.wellfound import WellfoundAdapter
from jobharness.sources.linkedin import LinkedInAdapter
from jobharness.sources.indeed import IndeedAdapter
from jobharness.sources.glassdoor import GlassdoorAdapter
from jobharness.sources.career_page.generic import GenericCareerPageAdapter
from jobharness.sources.career_page.browser_generic import CareerPageBrowserAdapter
from jobharness.sources.linkedin_guest import LinkedInGuestAdapter
from jobharness.profile import Profile


def test_adapters_import():
    assert InternshalaAdapter.name == "internshala"
    assert NaukriAdapter.name == "naukri"
    assert HiristAdapter.name == "hirist"
    assert WellfoundAdapter.name == "wellfound"
    assert LinkedInAdapter.name == "linkedin"
    assert IndeedAdapter.name == "indeed"
    assert GlassdoorAdapter.name == "glassdoor"
    assert GenericCareerPageAdapter.name == "career_page_generic"
    assert CareerPageBrowserAdapter.name == "career_page_browser"
    assert LinkedInGuestAdapter.name == "linkedin_guest"


def test_internshala_listing_slug_uses_keyword():
    prof = Profile(roles=["Backend Engineer"], keywords=["python"])
    slug = InternshalaAdapter._listing_slug(prof)
    assert slug == "python"


def test_internshala_listing_slug_falls_back_to_role():
    prof = Profile(roles=["Backend Engineer"])
    slug = InternshalaAdapter._listing_slug(prof)
    assert slug == "backend-engineer"


def test_internshala_listing_slug_sanitized():
    prof = Profile(roles=["Backend Engineer"], keywords=["Python (Django)"])
    slug = InternshalaAdapter._listing_slug(prof)
    assert slug == "python-django"


def test_internshala_listing_slug_role_words_joined():
    prof = Profile(roles=["Senior / Lead Engineer"])
    slug = InternshalaAdapter._listing_slug(prof)
    assert slug == "senior-/-lead-engineer"


def test_naukri_login_wall_detected():
    class FakePage:
        def __init__(self, url, has_login=False):
            self._url = url
            self._has_login = has_login

        @property
        def url(self):
            return self._url

        def query_selector(self, sel):
            return object() if self._has_login else None

    adapter = NaukriAdapter()
    assert adapter._login_wall(FakePage("https://www.naukri.com/login")) is True
    assert adapter._login_wall(FakePage("https://www.naukri.com/jobs", has_login=True)) is True
    assert adapter._login_wall(FakePage("https://www.naukri.com/jobs")) is False


def test_detect_block_captcha():
    class Page:
        def content(self):
            return "Verify you are human to continue"

    assert detect_block(Page()) == "captcha"


def test_detect_block_denied():
    class Page:
        def content(self):
            return "Access denied. Unusual traffic from your network."

    assert detect_block(Page()) == "denied"


def test_detect_block_clean():
    class Page:
        def content(self):
            return "Jobs list. Apply now."

    assert detect_block(Page()) == ""


def test_detect_block_exception_returns_empty():
    class BrokenPage:
        def content(self):
            raise RuntimeError("page crashed")

    assert detect_block(BrokenPage()) == ""