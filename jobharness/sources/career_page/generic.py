from __future__ import annotations

from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client, random_delay
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
        for company, seed in seeds:
            random_delay()
            with make_client() as client:
                try:
                    resp = client.get(seed)
                except Exception:
                    continue
                if resp.status_code != 200:
                    continue
            out.extend(extract_jobpostings_from_html(resp.text, self.name, seed, company))
        return out
