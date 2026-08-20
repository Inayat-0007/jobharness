from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client, random_delay


class GenericCareerPageAdapter(SourceAdapter):
    """Scrape schema.org JobPosting JSON-LD from a list of career page URLs.

    Uses profile.company_allowlist as a list of seed career URLs.
    Authentic fields come strictly from the JSON-LD block (no invention).
    """

    name = "career_page_generic"

    def fetch(self, profile: Profile) -> list[RawJob]:
        urls = []
        for c in profile.company_allowlist or []:
            if isinstance(c, dict):
                u = c.get("url")
                company = c.get("company", "")
            else:
                u = str(c)
                company = ""
            if u:
                urls.append((company, u))
        out: list[RawJob] = []
        for company, seed in urls:
            random_delay()
            with make_client() as client:
                resp = client.get(seed)
                if resp.status_code != 200:
                    continue
            soup = BeautifulSoup(resp.text, "lxml")
            for script in soup.select('script[type="application/ld+json"]'):
                try:
                    blob = json.loads(script.string or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue
                postings = blob if isinstance(blob, list) else [blob]
                for bp in postings:
                    if bp.get("@type") not in ("JobPosting", ["JobPosting"]):
                        continue
                    out.append(self._from_ld(bp, company, seed))
        return out

    def _from_ld(self, ld: dict, company_fallback: str, seed: str) -> RawJob:
        title = ld.get("title", "")
        org = ld.get("hiringOrganization") or {}
        company = (org.get("name") if isinstance(org, dict) else "") or company_fallback
        loc = ld.get("jobLocation") or ld.get("applicantLocationRequirements") or {}
        if isinstance(loc, dict):
            addr = loc.get("address", {})
            loc_str = ", ".join(
                str(v) for v in (addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")) if v
            )
        else:
            loc_str = str(loc)
        posted = ld.get("datePosted", "")
        valid_through = ld.get("validThrough", "")
        apply_url = ld.get("url", "")
        desc = ld.get("description", "")
        employment = ld.get("employmentType", "")
        salary = ld.get("baseSalary", {})
        salary_str = ""
        if isinstance(salary, dict):
            rng = salary.get("baseSalary") or salary
            if isinstance(rng, dict):
                val = rng.get("value", {})
                if isinstance(val, dict) and val.get("minValue"):
                    salary_str = f"{val.get('minValue')}-{val.get('maxValue')} {rng.get('currency','')}"
        return RawJob(
            source_name=self.name,
            source_url=seed,
            title=title,
            company=company,
            location=loc_str,
            description=desc,
            posted_date=posted,
            apply_url=apply_url,
            extra={"valid_through": valid_through, "employment_type": employment, "salary": salary_str},
        )
