from __future__ import annotations

import html as _html
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlunparse

from ..fetcher import get_shared_client, make_client, random_delay, resp_text
from ..models import RawJob
from ..profile import Profile
from .base import SourceAdapter

_LOGGER = logging.getLogger(__name__)

_LI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class LinkedInGuestAdapter(SourceAdapter):
    """Scrape LinkedIn's public guest jobs API (no login, no browser).

    LinkedIn exposes a logged-out search endpoint at
    ``/jobs-guest/jobs/api/seeMoreJobPostings/search`` that returns HTML job
    cards for any query. Cards are parsed with regex (no JSON-LD, no DOM
    required) and paginated up to 50 jobs per run. Each job's detail page is
    then fetched over plain HTTP to enrich the description (from the
    ``show-more-less-html__markup`` block), so the matcher sees the full
    posting text. Titles include fresher-specific labels like "Fresher",
    "Graduate Developer", "Assoc Software Engineer".

    No login, no CAPTCHA, no browser - pure HTTP with a realistic UA.
    """

    name = "linkedin_guest"
    _max_pages = 10

    def fetch(self, profile: Profile) -> list[RawJob]:
        import urllib.parse as up

        what = " ".join(profile.roles[:1] + ["fresher"]) or "Software Engineer"
        where = profile.location or "India"
        out: list[RawJob] = []
        for page in range(self._max_pages):
            start = page * 25
            url = (
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                + up.urlencode(
                    {
                        "keywords": what,
                        "location": where,
                        "f_TPR": "r86400",
                        "sortBy": "DD",
                        "start": str(start),
                    }
                )
            )
            random_delay()
            try:
                with make_client(timeout=20.0) as client:
                    resp = client.get(url, headers={"User-Agent": _LI_UA, "Referer": "https://www.linkedin.com/jobs/"})
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            jobs = self._parse(resp_text(resp), where)
            if not jobs:
                break
            out.extend(jobs)
            if len(out) >= 50:
                break
        if out:
            self._enrich(out, profile.enrich_cap)
        return out

    def _parse(self, html: str, where: str) -> list[RawJob]:
        out: list[RawJob] = []
        for block in re.split(r"<li\b", html)[1:]:
            try:
                href_m = re.search(r'base-card__full-link[^>]*href="([^"]+)"', block)
                title_m = re.search(r"base-search-card__title[^>]*>(.*?)</h3>", block, re.S)
                company_m = re.search(r"hidden-nested-link[^>]*>\s*(.*?)\s*</a>", block, re.S)
                loc_m = re.search(r"job-search-card__location[^>]*>\s*(.*?)\s*</span>", block, re.S)
                date_m = re.search(r'<time[^>]*datetime="([^"]+)"', block)
                href = _html.unescape(href_m.group(1)) if href_m else ""
                title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
                company = re.sub(r"<[^>]+>", "", company_m.group(1)).strip() if company_m else ""
                loc = re.sub(r"<[^>]+>", "", loc_m.group(1)).strip() if loc_m else ""
                posted = date_m.group(1) if date_m else ""
                if not title or not href:
                    continue
                out.append(
                    RawJob(
                        source_name=self.name,
                        source_url=href,
                        title=title,
                        company=company or "",
                        location=loc or where,
                        description="",
                        posted_date=posted,
                        apply_url=href,
                    )
                )
            except Exception:
                continue
        return out

    def _enrich(self, jobs: list, cap: int = 50) -> None:
        """Fetch the first `cap` jobs' detail pages and pull descriptions.

        LinkedIn rate-limits guest detail pages after ~20 requests per burst
        (HTTP 999). The cap comes from profile.enrich_cap (default 50), with
        an automatic retry on 999, so the freshest, most relevant jobs get
        descriptions. Later jobs fall back to title-only matching, which
        still catches roles with keywords in the title (e.g. "Python
        Developer").

        All requests go through the shared client (which carries the session
        cookies from the search pages), and a warm-up GET to the jobs home
        page seeds bcookie/li_sugr before the burst. A circuit breaker aborts
        the burst after 3 consecutive 999s so we don't keep burning requests.
        """
        to_enrich = jobs[:cap]
        self._warm_up_cookies()

        breaker = {"consecutive_999": 0}
        lock = threading.Lock()
        abort = {"flag": False}

        def _one(job: RawJob, retries: int = 1) -> None:
            random_delay()
            if abort["flag"]:
                return
            clean = urlunparse(urlparse(str(job.apply_url or ""))._replace(query=""))
            try:
                resp = get_shared_client(timeout=20.0).get(
                    clean,
                    headers={"User-Agent": _LI_UA, "Referer": "https://www.linkedin.com/jobs/"},
                )
            except Exception:
                return
            if resp.status_code == 999:
                with lock:
                    breaker["consecutive_999"] += 1
                    hits = breaker["consecutive_999"]
                if hits >= 3:
                    abort["flag"] = True
                    return
                if retries > 0:
                    time.sleep(5)
                    _one(job, retries=0)
                return
            with lock:
                breaker["consecutive_999"] = 0
            if resp.status_code != 200:
                return
            job.description = self._extract_desc(resp_text(resp))

        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(_one, j) for j in to_enrich]
            for fut in as_completed(futs):
                if abort["flag"]:
                    for f in futs:
                        f.cancel()
                    break
                try:
                    fut.result()
                except Exception:
                    pass
        if abort["flag"]:
            _LOGGER.warning(
                "linkedin_guest: enrichment aborted after 3 consecutive HTTP 999 "
                "(rate-limited); %d job(s) left without descriptions",
                sum(1 for j in to_enrich if not j.description),
            )

    @staticmethod
    def _warm_up_cookies() -> None:
        """Seed session cookies (bcookie, li_sugr) on the shared client.

        The shared client carries cookies from the search pages; a single
        GET to the jobs home page before the detail burst makes detail
        requests look like the same logged-out session instead of fresh
        sessions that LinkedIn rate-limits immediately.
        """
        try:
            get_shared_client(timeout=20.0).get(
                "https://www.linkedin.com/jobs/",
                headers={"User-Agent": _LI_UA, "Referer": "https://www.linkedin.com/"},
            )
        except Exception:
            pass

    @staticmethod
    def _extract_desc(html: str) -> str:
        i = html.find("show-more-less-html__markup")
        if i < 0:
            return ""
        seg = html[i : i + 12000]
        seg = re.sub(r"<script.*?</script>|<style.*?</style>", " ", seg, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", seg)
        text = re.sub(r"\s+", " ", text).strip()
        cut = text.lower().find("show more show less")
        if cut > 0:
            text = text[:cut]
        return text.strip()[:4000]
