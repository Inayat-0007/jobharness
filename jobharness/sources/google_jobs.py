from __future__ import annotations

import time
import urllib.parse

from ..fetcher import blocked_response, make_client, random_delay, resp_text
from ..models import RawJob
from ..profile import Profile
from .base import SourceAdapter
from .exceptions import BlockedError, RateLimitedError, SourceDownError
from .jobposting_ld import extract_jobpostings_from_blob, extract_jobpostings_from_html

GOOGLE_JOBS_URL = "https://www.google.com/search?q={query}&ibp=htl;jobs"

SHELL_BLOCKED_MSG = "google_jobs: jobs vertical redirected to web shell"

# Markers Google serves on the JS-only shell (udm=8 results page) that it
# redirects HTTP clients to when the jobs vertical blocks non-browser agents.
SHELL_MARKERS = ("enable javascript", "unusual traffic", "recaptcha", "<noscript>")


class GoogleJobsAdapter(SourceAdapter):
    """Best-effort scrape of Google's Jobs panel structured data (Tier 3).

    JS-rendered and detection-prone: uses retry with jittered backoff and
    falls back through (1) embedded JobPosting JSON-LD / @graph extraction,
    (2) Google's embedded job-results JSON, then (3) empty. Never invents data.
    """

    name = "google_jobs"

    def fetch(self, profile: Profile) -> list[RawJob]:
        terms = profile.roles[:1] + profile.keywords[:2] or ["software+engineer"]
        query = "+".join(urllib.parse.quote_plus(t) for t in terms)
        loc = profile.location or ("remote" if profile.remote else "")
        if loc:
            query += "+" + urllib.parse.quote_plus(loc)
        base = GOOGLE_JOBS_URL.format(query=query)
        variants = [
            base,
            base + "&hl=en&gl=in&num=20",
            base + "&gbv=1&hl=en&gl=in&num=20",
        ]
        shells = 0
        for url in variants:
            out: list[RawJob] = []
            shelled = False
            for attempt in range(3):
                random_delay(1.0, 3.0)
                try:
                    out = self._fetch_once(query, url)
                except BlockedError as exc:
                    if str(exc) != SHELL_BLOCKED_MSG:
                        raise
                    shelled = True
                    break
                if out:
                    return out
                if attempt < 2:
                    time.sleep(2 ** attempt)
            if shelled:
                shells += 1
                continue
            return out
        if shells == len(variants):
            raise BlockedError(SHELL_BLOCKED_MSG)
        return out

    def _is_shell(self, resp) -> bool:
        """True when Google dropped the jobs vertical and served the JS shell.

        After following redirects the final URL loses the `ibp=htl;jobs`
        parameter (udm=8 shell), and/or the body carries anti-bot/JS-only
        markers that never appear on the server-rendered jobs page.
        """
        if "ibp=htl;jobs" not in str(resp.url):
            return True
        body = resp_text(resp)[:5000].lower()
        return any(m in body for m in SHELL_MARKERS)

    def _fetch_once(self, query: str, url: str | None = None) -> list[RawJob]:
        url = url or GOOGLE_JOBS_URL.format(query=query)
        with make_client() as client:
            try:
                resp = client.get(url)
            except Exception:
                return []
            if resp.status_code == 429:
                raise RateLimitedError(f"{self.name}: rate limited (HTTP 429)")
            if resp.status_code in (401, 403) or blocked_response(resp):
                raise BlockedError(f"{self.name}: blocked response (HTTP {resp.status_code})")
            if self._is_shell(resp):
                raise BlockedError(SHELL_BLOCKED_MSG)
            if resp.status_code != 200:
                raise SourceDownError(f"{self.name}: HTTP {resp.status_code}")
            html = resp_text(resp)
        # Path 1: proper schema.org JobPosting JSON-LD blocks.
        out = extract_jobpostings_from_html(html, self.name, url)
        if out:
            return out
        # Path 2: Google embeds job results inside <script> blobs that contain
        # JobPosting objects (sometimes escaped JSON). Scan for any JSON object
        # containing a "JobPosting" type marker.
        import json
        import re

        out2: list[RawJob] = []
        for m in re.finditer(r"\{[^{}]*JobPosting[^{}]*\}", html):
            try:
                blob = json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
            out2.extend(extract_jobpostings_from_blob(blob, self.name, url))
        return out2
