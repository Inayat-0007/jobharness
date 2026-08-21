from __future__ import annotations

import time

from .base import SourceAdapter
from ..models import RawJob
from ..profile import Profile
from ..browser import (
    open_browser,
    wait_for_captcha,
    detect_block,
    scroll_to_load,
    wait_for_selector_any,
)


class GlassdoorAdapter(SourceAdapter):
    name = "glassdoor"

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
        where = profile.location or ""
        url = (
            "https://www.glassdoor.com/Job/jobs.htm?sc.keyword="
            + up.quote(what)
            + ("&locT=C&locId=" + up.quote(where) if where else "")
            + "&fromAge=7&sort=date_desc"
        )
        out: list[RawJob] = []
        with open_browser(self.name, headless=False, mobile=mobile) as (_p, browser):
            page = browser.pages[0] if browser.pages else browser.new_page()
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception:
                pass
            time.sleep(5 if not mobile else 3)
            block = detect_block(page)
            if block:
                if block == "captcha":
                    if not wait_for_captcha(page, self.name, timeout=600):
                        if not mobile:
                            raise RuntimeError(f"captcha wait timed out")
                        return out
                    time.sleep(3)
                else:
                    if not mobile:
                        raise RuntimeError(f"blocked: {block}")
                    return out
            if not wait_for_selector_any(
                page,
                [
                    "li.react-job-listing",
                    "[data-test='job-link']",
                    "[data-test='job-title']",
                    "a.jobLink",
                    "li.react-job-listing-Green",
                ],
                timeout=20000,
            ):
                if not page.query_selector("li.react-job-listing, a.jobLink, [data-test='job-title']"):
                    return out
            scroll_to_load(page, max_scrolls=8, pause=0.8)
            cards = page.query_selector_all(
                "li.react-job-listing, [data-test='job-link'], li.react-job-listing-Green"
            )
            seen = 0
            for c in cards:
                if seen >= profile.top_n:
                    break
                try:
                    title_el = c.query_selector(
                        "a.jobLink, [data-test='job-title'], a[data-test='job-link'] span"
                    )
                    title_txt = (title_el.inner_text() if title_el else "").strip()
                    company = c.query_selector(".employerName, [data-test='employer-name']")
                    company_txt = (company.inner_text() if company else "").strip()
                    loc = c.query_selector(".loc, [data-test='emp-location']")
                    loc_txt = (loc.inner_text() if loc else "").strip()
                    a = c.query_selector("a[href*='/job-listing/'], a.jobLink")
                    href = a.get_attribute("href") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://www.glassdoor.com" + href
                    if not title_txt or not href:
                        continue
                    out.append(
                        RawJob(
                            source_name=self.name,
                            source_url=href,
                            title=title_txt,
                            company=company_txt,
                            location=loc_txt or where,
                            apply_url=href,
                        )
                    )
                    seen += 1
                except Exception:
                    continue
        return out
