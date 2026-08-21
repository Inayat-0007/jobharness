from __future__ import annotations

import html as _html
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlunparse

from .base import SourceAdapter
from ..models import RawJob
from ..profile import Profile
from ..fetcher import make_client, random_delay, resp_text

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
            self._enrich(out)
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

    def _enrich(self, jobs: list) -> None:
        """Fetch the first 20 jobs' detail pages and pull descriptions.

        LinkedIn rate-limits guest detail pages after ~20 requests per burst
        (HTTP 999). We cap at 20, with an automatic retry on 999, so the
        freshest, most relevant jobs get descriptions. Later jobs fall back
        to title-only matching, which still catches roles with keywords in
        the title (e.g. "Python Developer").
        """
        to_enrich = jobs[:20]

        def _one(job: RawJob, retries: int = 1) -> None:
            random_delay()
            clean = urlunparse(urlparse(job.apply_url)._replace(query=""))
            try:
                with make_client(timeout=20.0) as client:
                    resp = client.get(
                        clean,
                        headers={"User-Agent": _LI_UA, "Referer": "https://www.linkedin.com/jobs/"},
                    )
            except Exception:
                return
            if resp.status_code == 999 and retries > 0:
                time.sleep(5)
                _one(job, retries=0)
                return
            if resp.status_code != 200:
                return
            job.description = self._extract_desc(resp_text(resp))

        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = [ex.submit(_one, j) for j in to_enrich]
            for fut in as_completed(futs):
                try:
                    fut.result()
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