from __future__ import annotations

import time

from .base import SourceAdapter
from ..models import RawJob
from ..profile import Profile
from ..browser import cookie_path, pick_proxy, manual_captcha_wait


class LinkedInAdapter(SourceAdapter):
    """Login-gated LinkedIn jobs scraper (Tier 5).

    Uses headed Playwright with stealth, persistent cookies, and a MANUAL
    human CAPTCHA gate (the run pauses until the user solves the CAPTCHA).
    No automated captcha solving. No invention of data - title/url/sourced.
    """

    name = "linkedin"

    def fetch(self, profile: Profile) -> list[RawJob]:
        return self._fetch_playwright(profile)

    def _fetch_playwright(self, profile: Profile) -> list[RawJob]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []
        import urllib.parse as up

        what = " ".join(profile.roles[:1] + profile.keywords[:2]) or "Software Engineer"
        where = profile.location or ("Remote" if profile.remote else "")
        url = (
            "https://www.linkedin.com/jobs/search/?keywords="
            + up.quote(what)
            + ("&f_WT=2" if profile.remote else "")
            + ("&location=" + up.quote(where) if where else "")
            + "&f_TPR=r86400"
            + "&sortBy=DD"
        )
        out: list[RawJob] = []
        cpath = str(cookie_path(self.name))
        proxy_opts = {"server": pick_proxy()} if pick_proxy() else None
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                cpath, headless=False, proxy=proxy_opts, viewport={"width": 1366, "height": 900}
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception:
                pass
            time.sleep(4)
            if self._captcha_present(page):
                manual_captcha_wait(self.name, True)
                time.sleep(3)
            try:
                page.wait_for_selector("li.jobs-search-results__list-item, div.job-card-container", timeout=20000)
            except Exception:
                browser.close()
                return out
            cards = page.query_selector_all("li.jobs-search-results__list-item, div.job-card-container")
            for c in cards[: profile.top_n]:
                try:
                    a = c.query_selector("a.job-card-container__link, a[href*='/jobs/view/']")
                    title = c.query_selector(".job-card-container__link, h3")
                    title_txt = (title.inner_text() if title else "").strip()
                    company = c.query_selector(".job-card-container__company-name, h4")
                    company_txt = (company.inner_text() if company else "").strip()
                    loc = c.query_selector(".job-card-container__metadata-item, li.job-card-container__metadata-item")
                    loc_txt = (loc.inner_text() if loc else "").strip()
                    href = a.get_attribute("href") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://www.linkedin.com" + href
                    posted = (c.inner_text() or "")
                    out.append(
                        RawJob(
                            source_name=self.name,
                            source_url=href,
                            title=title_txt,
                            company=company_txt,
                            location=loc_txt or where,
                            description="",
                            posted_date=self._extract_age(posted),
                            apply_url=href,
                        )
                    )
                except Exception:
                    continue
            browser.close()
        return out

    def _captcha_present(self, page) -> bool:
        markers = ["captcha", "verify you are human", "security verification"]
        try:
            content = (page.content() or "").lower()
            return any(m in content for m in markers)
        except Exception:
            return False

    def _extract_age(self, text: str) -> str:
        for tok in ("1 day ago", "2 days ago", "just now", "1 hour ago", "today", "week ago"):
            if tok in text.lower():
                return tok
        return ""
