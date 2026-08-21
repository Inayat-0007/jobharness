from __future__ import annotations

import logging
import time

from ..browser import (
    detect_block,
    open_browser,
    scroll_to_load,
    wait_for_captcha,
    wait_for_selector_any,
)
from ..models import RawJob
from ..profile import Profile
from .base import SourceAdapter, raise_navigation_failure
from .exceptions import BlockedError

logger = logging.getLogger(__name__)


class IndeedAdapter(SourceAdapter):
    name = "indeed"

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
            "https://in.indeed.com/jobs?q="
            + up.quote(what)
            + "&fromage=7&sort=date"
            + ("&sc=0kf%3Aattr(DSQF7)%3B" if profile.remote else "")
            + ("&l=" + up.quote(where) if where else "")
        )
        out: list[RawJob] = []
        with open_browser(
            self.name,
            headless=False,
            mobile=mobile,
            timezone_id="Asia/Kolkata",
            locale="en-IN",
        ) as (_p, browser):
            page = browser.pages[0] if browser.pages else browser.new_page()
            goto_err = None
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception as e:
                goto_err = e
            time.sleep(4 if not mobile else 3)
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
                    "div.job_seen_beacon",
                    ".result",
                    "[data-jk]",
                    "[data-testid='job-card']",
                    "div.css-1m4cu4y",
                ],
                timeout=20000,
            ):
                if not page.query_selector("div.job_seen_beacon, [data-jk], a[href*='/jobs/']"):
                    if goto_err is not None:
                        raise_navigation_failure(self.name, page, goto_err)
                    return out
            scroll_to_load(page, max_scrolls=8, pause=0.7)
            cards = page.query_selector_all(
                "div.job_seen_beacon, .result, [data-jk], [data-testid='job-card']"
            )
            seen = 0
            for c in cards:
                if seen >= profile.top_n:
                    break
                try:
                    title = c.query_selector(
                        "h2.jobTitle, .jobTitle span, a[href*='/jobs/'], [data-testid='job-title'] span, span"
                    )
                    title_txt = (title.inner_text() if title else "").strip()
                    company = c.query_selector(
                        ".companyName, [data-testid='company-name'], .css-1h4635t"
                    )
                    company_txt = (company.inner_text() if company else "").strip()
                    loc = c.query_selector(
                        ".companyLocation, [data-testid='text-location'], .css-1p0sjll"
                    )
                    loc_txt = (loc.inner_text() if loc else "").strip()
                    a = c.query_selector("a[href*='/jobs/']")
                    href = a.get_attribute("href") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://in.indeed.com" + href
                    age = c.query_selector(".date, [data-testid='myTime-state'], .css-1hv8ot2")
                    age_txt = (age.inner_text() if age else "").strip()
                    if not title_txt or not href:
                        continue
                    out.append(
                        RawJob(
                            source_name=self.name,
                            source_url=href,
                            title=title_txt,
                            company=company_txt,
                            location=loc_txt or where,
                            posted_date=age_txt,
                            apply_url=href,
                        )
                    )
                    seen += 1
                except Exception as e:
                    logger.debug("indeed card parse skipped: %s", e)
                    continue
        if not out and goto_err is not None:
            raise_navigation_failure(self.name, page, goto_err)
        return out
