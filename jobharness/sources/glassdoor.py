from __future__ import annotations

import time

from .base import SourceAdapter
from ..models import RawJob
from ..profile import Profile
from ..browser import cookie_path, pick_proxy, manual_captcha_wait


class GlassdoorAdapter(SourceAdapter):
    name = "glassdoor"

    def fetch(self, profile: Profile) -> list[RawJob]:
        return self._fetch_playwright(profile)

    def _fetch_playwright(self, profile: Profile) -> list[RawJob]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []
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
                page.wait_for_selector("li.react-job-listing, [data-test='job-link']", timeout=20000)
            except Exception:
                browser.close()
                return out
            cards = page.query_selector_all("li.react-job-listing, [data-test='job-link'], li")
            seen = 0
            for c in cards:
                if seen >= profile.top_n:
                    break
                try:
                    title_el = c.query_selector("a.jobLink, [data-test='job-title']")
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
            browser.close()
        return out

    def _captcha_present(self, page) -> bool:
        markers = ["captcha", "are you human", "trust and safety"]
        try:
            return any(m in (page.content() or "").lower() for m in markers)
        except Exception:
            return False
