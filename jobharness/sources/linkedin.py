from __future__ import annotations

import logging
import time

from ..browser import (
    detect_block,
    open_browser,
    scroll_to_load,
    wait_for_captcha,
    wait_for_login,
    wait_for_selector_any,
)
from ..models import RawJob
from ..profile import Profile
from .base import SourceAdapter, raise_navigation_failure
from .exceptions import AuthRequiredError, BlockedError

logger = logging.getLogger(__name__)


class LinkedInAdapter(SourceAdapter):
    """Login-gated LinkedIn jobs scraper (Tier 5).

    Headed Playwright + stealth + persistent cookies + manual human gates
    (CAPTCHA and first-login). If LinkedIn shows a sign-in wall, the run pauses
    for a manual login; cookies persist for later runs. Retries with a mobile
    context on block, scrolls to load lazy cards, uses resilient selectors.
    No automated captcha solving; no invented data.
    """

    name = "linkedin"

    def fetch(self, profile: Profile) -> list[RawJob]:
        last_err = None
        for mobile in (False, True):
            try:
                return self._fetch(profile, mobile=mobile)
            except Exception as e:
                last_err = e
        if last_err is not None:
            print(f"[{self.name}] all attempts failed: {last_err}")
            raise last_err
        return []

    def _fetch(self, profile: Profile, mobile: bool = False) -> list[RawJob]:
        import urllib.parse as up

        what = " ".join(profile.roles[:1] + ["fresher"]) or "Software Engineer"
        where = profile.location or ("Remote" if profile.remote else "")
        url = (
            "https://www.linkedin.com/jobs/search/?keywords="
            + up.quote(what)
            + ("&f_WT=2" if profile.remote else "")
            + ("&location=" + up.quote(where) if where else "")
            + "&f_TPR=r86400&sortBy=DD"
        )
        out: list[RawJob] = []
        with open_browser(self.name, headless=False, mobile=mobile) as (_p, browser):
            page = browser.pages[0] if browser.pages else browser.new_page()
            goto_err = None
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception as e:
                goto_err = e
            time.sleep(4 if not mobile else 3)
            if self._login_wall(page):
                if not wait_for_login(page, self.name, url, self._login_wall, timeout=300):
                    raise AuthRequiredError(f"{self.name}: login wait timed out")
            block = detect_block(page)
            if block:
                if block == "captcha":
                    if not wait_for_captcha(page, self.name, timeout=600):
                        raise BlockedError(f"{self.name}: captcha wait timed out")
                    time.sleep(3)
                else:
                    raise BlockedError(f"{self.name}: blocked: {block}")
            if not wait_for_selector_any(
                page,
                [
                    "li.jobs-search-results__list-item",
                    "div.job-card-container",
                    "[data-job-id]",
                    "div.scaffold-layout__list-container li",
                    "a.job-card-list__title",
                ],
                timeout=20000,
            ):
                if not page.query_selector("li.jobs-search-results__list-item, div.job-card-container, a[href*='/jobs/view/']"):
                    if goto_err is not None:
                        raise_navigation_failure(self.name, page, goto_err)
                    return out
            scroll_to_load(page, max_scrolls=8, pause=0.7)
            cards = page.query_selector_all(
                "li.jobs-search-results__list-item, div.job-card-container, "
                "div.scaffold-layout__list-container li, [data-job-id]"
            )
            seen = 0
            for c in cards:
                if seen >= profile.top_n:
                    break
                try:
                    a = c.query_selector(
                        "a.job-card-container__link, a[href*='/jobs/view/'], a.job-card-list__title, a"
                    )
                    title = c.query_selector(
                        ".job-card-container__link, h3, .job-card-list__title, a[href*='/jobs/view/'] span"
                    )
                    title_txt = (title.inner_text() if title else "").strip()
                    company = c.query_selector(
                        ".job-card-container__company-name, h4, .job-card-container__primary-description, "
                        ".artdeco-entity-lockup__subtitle"
                    )
                    company_txt = (company.inner_text() if company else "").strip()
                    loc = c.query_selector(
                        ".job-card-container__metadata-item, li.job-card-container__metadata-item, "
                        ".job-card-container__metadata-wrapper, .artdeco-entity-lockup__caption"
                    )
                    loc_txt = (loc.inner_text() if loc else "").strip()
                    href = a.get_attribute("href") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://www.linkedin.com" + href
                    if not title_txt or not href:
                        continue
                    body_text = (c.inner_text() or "")
                    out.append(
                        RawJob(
                            source_name=self.name,
                            source_url=href,
                            title=title_txt,
                            company=company_txt,
                            location=loc_txt or where,
                            description="",
                            posted_date=self._extract_age(body_text),
                            apply_url=href,
                        )
                    )
                    seen += 1
                except Exception as e:
                    logger.debug("linkedin card parse skipped: %s", e)
                    continue
        if not out and goto_err is not None:
            raise_navigation_failure(self.name, page, goto_err)
        return out

    def _login_wall(self, page) -> bool:
        """True when LinkedIn is showing a sign-in wall instead of search results."""
        u = (page.url or "").lower()
        if any(t in u for t in ("/login", "/checkpoint/", "/authwall", "/uas/")):
            return True
        return page.query_selector(
            "#session_key, #login-email, input[name='session_key'], form.login"
        ) is not None

    def _extract_age(self, text: str) -> str:
        t = text.lower()
        for tok in (
            "just now", "today", "1 hour ago", "2 hours ago", "3 hours ago",
            "1 day ago", "2 days ago", "3 days ago", "1 week ago", "2 weeks ago",
            "active 1 day ago", "active 2 days ago",
        ):
            if tok in t:
                return tok
        for m in ("day ago", "days ago", "week ago", "weeks ago", "hour ago", "hours ago"):
            if m in t:
                return m
        return ""
