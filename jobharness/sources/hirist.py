from __future__ import annotations

import random
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


class HiristAdapter(SourceAdapter):
    """Login-gated Hirist.com tech-jobs scraper (Tier 5).

    Headed Playwright + stealth + persistent cookies + manual human gates
    (CAPTCHA and first-login). Fresher experience filter via `experience=0-1`.
    """

    name = "hirist"

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
        url = (
            "https://hirist.com/tech-jobs?searchText="
            + up.quote(what)
            + "&location="
            + up.quote(profile.location or "India")
            + "&experience=0-1"
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
            time.sleep(random.uniform(1.5, 3.0))
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
                    ".job-box",
                    ".card.job-card",
                    "[data-jid]",
                    ".job-card",
                ],
                timeout=20000,
            ):
                if not page.query_selector(".job-box, .card.job-card, [data-jid]"):
                    if goto_err is not None:
                        raise_navigation_failure(self.name, page, goto_err)
                    return out
            scroll_to_load(page, max_scrolls=8, pause=0.8)
            cards = page.query_selector_all(
                ".job-box, .card.job-card, [data-jid]"
            )
            seen = 0
            for c in cards:
                if seen >= profile.top_n:
                    break
                try:
                    title_el = c.query_selector(".job-title, h2 a, h2")
                    title_txt = (title_el.inner_text() if title_el else "").strip()
                    company = c.query_selector(".company-name, .employer-name, .company")
                    company_txt = (company.inner_text() if company else "").strip()
                    loc = c.query_selector(".job-location, .location")
                    loc_txt = (loc.inner_text() if loc else "").strip()
                    a = c.query_selector("a[href*='/job/'], a.job-title, a")
                    href = a.get_attribute("href") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://hirist.com" + href
                    exp_el = c.query_selector(".job-exp, .exp")
                    exp_txt = (exp_el.inner_text() if exp_el else "").strip()
                    sal_el = c.query_selector(".job-salary, .salary")
                    sal_txt = (sal_el.inner_text() if sal_el else "").strip()
                    date_el = c.query_selector(".job-posted, .posted-date")
                    date_txt = (date_el.inner_text() if date_el else "").strip()
                    if not title_txt or not href:
                        continue
                    extra = {}
                    if sal_txt:
                        extra["salary"] = sal_txt
                    if exp_txt:
                        extra["experience_needed"] = exp_txt
                    out.append(
                        RawJob(
                            source_name=self.name,
                            source_url=href,
                            title=title_txt,
                            company=company_txt,
                            location=loc_txt or profile.location or "",
                            description="",
                            posted_date=date_txt,
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

    def _login_wall(self, page) -> bool:
        """True when Hirist redirected to a login page or shows a login form."""
        if "/login" in (page.url or "").lower():
            return True
        return page.query_selector(
            "form[action*='login'], .login-form, #loginModal, input[name='email']"
        ) is not None
