from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .base import SourceAdapter
from ..models import RawJob
from ..profile import Profile
from ..fetcher import make_client, random_delay


GOOGLE_JOBS_URL = "https://www.google.com/search?q={query}&ibp=htl;jobs"


class GoogleJobsAdapter(SourceAdapter):
    """Best-effort scrape of Google's Jobs panel structured data.

    Tier 3: JS-rendered, detection-prone. Extracts JobPosting JSON-LD / ls:data where
    available; degrades gracefully (empty list) instead of inventing data.
    """

    name = "google_jobs"

    def fetch(self, profile: Profile) -> list[RawJob]:
        query = "+".join((profile.roles[:1] + profile.keywords[:2])) or "software+engineer"
        loc = profile.location or ("remote" if profile.remote else "")
        if loc:
            query += "+" + loc.replace(" ", "+")
        url = GOOGLE_JOBS_URL.format(query=query)
        random_delay()
        out: list[RawJob] = []
        with make_client() as client:
            try:
                resp = client.get(url)
            except Exception:
                return out
            if resp.status_code != 200:
                return out
            text = resp.text or ""
        # Google embeds jobs data in scripts as JSON containing "JobPosting" objects.
        for match in re.findall(r"(\{\"[^{}]*JobPosting.*?\})", text):
            try:
                blob = json.loads(match)
            except json.JSONDecodeError:
                continue
            out.append(self._from_blob(blob, url))
        # Fallback: regex over JSON-LD script tags rendered server-side
        soup = BeautifulSoup(text, "lxml")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                blob = json.loads(script.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            postings = blob if isinstance(blob, list) else [blob]
            for bp in postings:
                if bp.get("@type") not in ("JobPosting", ["JobPosting"]):
                    continue
                out.append(self._from_blob(bp, url))
        return out

    def _from_blob(self, ld: dict, base_url: str) -> RawJob:
        org = ld.get("hiringOrganization") or {}
        company = org.get("name", "") if isinstance(org, dict) else ""
        loc = ld.get("jobLocation") or {}
        loc_str = ""
        if isinstance(loc, dict):
            a = loc.get("address", {})
            loc_str = ", ".join(str(v) for v in (a.get("addressLocality"), a.get("addressRegion")) if v)
        return RawJob(
            source_name=self.name,
            source_url=ld.get("url", base_url),
            title=ld.get("title", ""),
            company=company,
            location=loc_str,
            description=ld.get("description", ""),
            posted_date=ld.get("datePosted", ""),
            apply_url=ld.get("url", ""),
        )
