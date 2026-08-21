from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ...fetcher import make_client, random_delay, resp_text
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter
from ..jobposting_ld import extract_jobpostings_from_html


class GenericCareerPageAdapter(SourceAdapter):
    """Scrape schema.org JobPosting JSON-LD from a list of career page URLs.

    Uses profile.company_allowlist as a list of seed career URLs (strings or
    {company, url} dicts). Authentic fields come strictly from the JSON-LD
    block via the shared jobposting_ld parser (no invention).
    """

    name = "career_page_generic"

    def fetch(self, profile: Profile) -> list[RawJob]:
        seeds = []
        for c in profile.career_pages or [
            e for e in (getattr(profile, "company_allowlist", []) or []) if isinstance(e, dict) and e.get("url")
        ]:
            if isinstance(c, dict):
                u = c.get("url")
                company = c.get("company", "")
            elif isinstance(c, str):
                u = str(c)
                company = ""
            else:
                continue
            if u:
                seeds.append((company, u))
        out: list[RawJob] = []
        with ThreadPoolExecutor(max_workers=max(1, profile.career_fetch_workers)) as ex:
            futs = [ex.submit(self._fetch_seed, company, seed) for company, seed in seeds]
            for fut in futs:
                out.extend(fut.result())
        return out

    def _fetch_seed(self, company: str, seed: str) -> list[RawJob]:
        random_delay()
        with make_client() as client:
            try:
                resp = client.get(seed)
            except Exception:
                return []
            if resp.status_code != 200:
                return []
        return extract_jobpostings_from_html(resp_text(resp), self.name, seed, company)
