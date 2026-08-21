from __future__ import annotations

import random
import time

from .base import SourceAdapter
from .exceptions import RateLimitedError
from ..models import RawJob
from ..profile import Profile
from ..browser import (
    open_browser,
    wait_for_captcha,
    detect_block,
    scroll_to_load,
    wait_for_selector_any,
)


class WellfoundAdapter(SourceAdapter):
    """Wellfound (AngelList) jobs scraper (Tier 5, no login for search).

    Headed Playwright + stealth + persistent cookies + manual CAPTCHA gate.
    Global site — the profile's India/remote location filter in matcher.py
    rejects on-site postings outside India.
    """

    name = "wellfound"

    def fetch(self, profile: Profile) -> list[RawJob]:
        last_err = None
        for mobile in (False, True):
            try:
                return self._fetch(profile, mobile=mobile)
            except RateLimitedError as e:
                last_err = e
                if not mobile:
                    continue
                raise
            except Exception as e:
                last_err = e
                continue
        if last_err:
            print(f"[{self.name}] all attempts failed: {last_err}")
        return []

    def _fetch(self, profile: Profile, mobile: bool = False) -> list[RawJob]:
        import urllib.parse as up

        what = " ".join(profile.roles[:1] + ["fresher"]) or "Software Engineer"
        where = profile.location or "India"
        url = (
            "https://wellfound.com/jobs?location="
            + up.quote(where)
            + "&q="
            + up.quote(what)
        )
        out: list[RawJob] = []
        with open_browser(self.name, headless=False, mobile=mobile) as (_p, browser):
            page = browser.pages[0] if browser.pages else browser.new_page()
            time.sleep(random.uniform(1.5, 3.0))
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception:
                pass
            time.sleep(4 if not mobile else 3)
            block = detect_block(page)
            if block:
                if block == "captcha":
                    if not wait_for_captcha(page, self.name, timeout=600):
                        if not mobile:
                            raise RateLimitedError(f"{self.name}: captcha wait timed out")
                        return out
                    time.sleep(3)
                else:
                    if not mobile:
                        raise RateLimitedError(f"{self.name}: blocked: {block}")
                    return out
            if not wait_for_selector_any(
                page,
                [
                    "div[data-testid^='job-card']",
                    ".jobs-list-item",
                    ".job-card",
                ],
                timeout=20000,
            ):
                if not page.query_selector("div[data-testid^='job-card'], .jobs-list-item"):
                    return out
            scroll_to_load(page, max_scrolls=8, pause=0.8)
            cards = page.query_selector_all(
                "div[data-testid^='job-card'], .jobs-list-item"
            )
            seen = 0
            for c in cards:
                if seen >= profile.top_n:
                    break
                try:
                    title_el = c.query_selector(
                        "a[data-testid*='title'], h2, .job-title"
                    )
                    title_txt = (title_el.inner_text() if title_el else "").strip()
                    company = c.query_selector(
                        "[data-testid*='company'], .company-name, .company"
                    )
                    company_txt = (company.inner_text() if company else "").strip()
                    loc = c.query_selector("[data-testid*='location'], .location")
                    loc_txt = (loc.inner_text() if loc else "").strip()
                    a = c.query_selector("a[href*='/jobs/']")
                    href = a.get_attribute("href") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://wellfound.com" + href
                    if not title_txt or not href:
                        continue
                    out.append(
                        RawJob(
                            source_name=self.name,
                            source_url=href,
                            title=title_txt,
                            company=company_txt,
                            location=loc_txt or where,
                            description="",
                            apply_url=href,
                        )
                    )
                    seen += 1
                except Exception:
                    continue
        return out
