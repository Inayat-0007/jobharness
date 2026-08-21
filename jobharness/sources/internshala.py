from __future__ import annotations

import random
import re
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


class InternshalaAdapter(SourceAdapter):
    """Internshala internship scraper (Tier 5, no login).

    Headed Playwright + stealth + persistent cookies + manual CAPTCHA gate.
    Listing slug is derived from the first keyword/role (e.g. `python-internship`).
    """

    name = "internshala"

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

        slug = self._listing_slug(profile)
        url = "https://internshala.com/internships/" + up.quote(slug) + "-internship"
        out: list[RawJob] = []
        with open_browser(
            self.name,
            headless=False,
            mobile=mobile,
            timezone_id="Asia/Kolkata",
            locale="en-IN",
        ) as (_p, browser):
            page = browser.pages[0] if browser.pages else browser.new_page()
            time.sleep(random.uniform(1.5, 3.0))
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
                    ".individual_internship",
                    ".internship_meta",
                    "a[href*='/internship/detail/']",
                ],
                timeout=20000,
            ):
                if not page.query_selector(".individual_internship, a[href*='/internship/detail/']"):
                    if goto_err is not None:
                        raise_navigation_failure(self.name, page, goto_err)
                    return out
            scroll_to_load(page, max_scrolls=8, pause=0.8)
            cards = page.query_selector_all(
                ".individual_internship, .internship_meta"
            )
            seen = 0
            for c in cards:
                if seen >= profile.top_n:
                    break
                try:
                    title_el = c.query_selector(
                        "a[href*='/internship/detail/'], h3.heading_4_5, h3"
                    )
                    title_txt = (title_el.inner_text() if title_el else "").strip()
                    company = c.query_selector(".company_name, p.company-name, .company")
                    company_txt = (company.inner_text() if company else "").strip()
                    loc = c.query_selector(".locations, a.location_link, .location")
                    loc_txt = (loc.inner_text() if loc else "").strip()
                    a = c.query_selector("a[href*='/internship/detail/']")
                    href = a.get_attribute("href") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://internshala.com" + href
                    stip_el = c.query_selector(".stipend, #salary, .salary")
                    stip_txt = (stip_el.inner_text() if stip_el else "").strip()
                    posted_el = c.query_selector(".status_container, .post-by")
                    posted_txt = (posted_el.inner_text() if posted_el else "").strip()
                    if not title_txt or not href:
                        continue
                    extra = {"salary": stip_txt} if stip_txt else {}
                    out.append(
                        RawJob(
                            source_name=self.name,
                            source_url=href,
                            title=title_txt,
                            company=company_txt,
                            location=loc_txt or profile.location or "",
                            description="",
                            posted_date=posted_txt,
                            apply_url=href,
                            extra=extra,
                        )
                    )
                    seen += 1
                except Exception:
                    continue
        if not out and goto_err is not None:
            raise_navigation_failure(self.name, page, goto_err)
        return out

    @staticmethod
    def _listing_slug(profile: Profile) -> str:
        if profile.keywords:
            kw = re.sub(r"[^a-z0-9]+", "-", profile.keywords[0].lower()).strip("-")
            if kw:
                return kw
        words = profile.roles[0].lower().split() if profile.roles else ["internship"]
        return "-".join(words)
