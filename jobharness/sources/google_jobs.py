from __future__ import annotations

import time
import urllib.parse

from ..fetcher import blocked_response, make_client, random_delay, resp_text
from ..models import RawJob
from ..profile import Profile
from .base import SourceAdapter
from .exceptions import BlockedError
from .jobposting_ld import extract_jobpostings_from_blob, extract_jobpostings_from_html

GOOGLE_JOBS_URL = "https://www.google.com/search?q={query}&ibp=htl;jobs"


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
        out: list[RawJob] = []
        for attempt in range(3):
            random_delay(1.0, 3.0)
            out = self._fetch_once(query)
            if out:
                return out
            # backoff before retrying
            if attempt < 2:
                time.sleep(2 ** attempt)
        return out

    def _fetch_once(self, query: str) -> list[RawJob]:
        url = GOOGLE_JOBS_URL.format(query=query)
        with make_client() as client:
            try:
                resp = client.get(url)
            except Exception:
                return []
            if resp.status_code != 200:
                return []
            if blocked_response(resp):
                raise BlockedError(f"{self.name}: blocked response (HTTP {resp.status_code})")
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
