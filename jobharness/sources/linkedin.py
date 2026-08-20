from __future__ import annotations

import time

from .base import SourceAdapter
from ..models import RawJob
from ..profile import Profile
from ..browser import (
    open_browser,
    manual_captcha_wait,
    detect_block,
    scroll_to_load,
    wait_for_selector_any,
)


class LinkedInAdapter(SourceAdapter):
    """Login-gated LinkedIn jobs scraper (Tier 5).

    Headed Playwright + stealth + persistent cookies + manual human CAPTCHA gate.
    Retries with a mobile context on block, scrolls to load lazy cards, uses
    resilient selectors. No automated captcha solving; no invented data.
    """

    name = "linkedin"

    def fetch(self, profile: Profile) -> list[RawJob]:
        last_err = None
        for mobile in (False, True):
            try:
                return self._fetch(profile, mobile=mobile)
            except Exception as e:
                last_err = e
                continue
        if last_err:
            print(f"[{self.name}] all attempts failed: {last_err}")
        return []

    def _fetch(self, profile: Profile, mobile: bool = False) -> list[RawJob]:
        import urllib.parse as up

        what = " ".join(profile.roles[:1] + profile.keywords[:2]) or "Software Engineer"
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
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception:
                pass
            time.sleep(4 if not mobile else 3)
            block = detect_block(page)
            if block:
                if block == "captcha":
                    manual_captcha_wait(self.name, True)
                    time.sleep(3)
                else:
                    # denied / hard block -> try mobile fallback if not already mobile
                    if not mobile:
                        raise RuntimeError(f"blocked: {block}")
                    return out
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
                # after captcha solve, content may now be present
                if not page.query_selector("li.jobs-search-results__list-item, div.job-card-container, a[href*='/jobs/view/']"):
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
                except Exception:
                    continue
        return out

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
