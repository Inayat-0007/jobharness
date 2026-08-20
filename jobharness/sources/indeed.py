from __future__ import annotations

import time

from .base import SourceAdapter
from ..models import RawJob
from ..profile import Profile
from ..browser import cookie_path, pick_proxy, manual_captcha_wait


class IndeedAdapter(SourceAdapter):
    name = "indeed"

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
            "https://www.indeed.com/jobs?q="
            + up.quote(what)
            + "&fromage=7&sort=date"
            + ("&sc=0kf%3Aattr(DSQF7)%3B" if profile.remote else "")
            + ("&l=" + up.quote(where) if where else "")
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
                page.wait_for_selector("div.job_seen_beacon, .result, [data-jk]", timeout=20000)
            except Exception:
                browser.close()
                return out
            cards = page.query_selector_all("div.job_seen_beacon, .result, li")
            seen = 0
            for c in cards:
                if seen >= profile.top_n:
                    break
                try:
                    title = c.query_selector("h2.jobTitle, .jobTitle span, a[href*='/jobs/']")
                    title_txt = (title.inner_text() if title else "").strip()
                    company = c.query_selector(".companyName, [data-testid='company-name']")
                    company_txt = (company.inner_text() if company else "").strip()
                    loc = c.query_selector(".companyLocation, [data-testid='text-location']")
                    loc_txt = (loc.inner_text() if loc else "").strip()
                    a = c.query_selector("a[href*='/jobs/']")
                    href = a.get_attribute("href") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://www.indeed.com" + href
                    age = c.query_selector(".date, [data-testid='myTime-state']")
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
                except Exception:
                    continue
            browser.close()
        return out

    def _captcha_present(self, page) -> bool:
        markers = ["captcha", "are you a robot", "verify you"]
        try:
            return any(m in (page.content() or "").lower() for m in markers)
        except Exception:
            return False
