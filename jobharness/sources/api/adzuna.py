from __future__ import annotations

from ... import secrets
from ...fetcher import blocked_response, make_client, random_delay
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter
from ..exceptions import BlockedError, ParseFailureError

COUNTRY_NAMES = {
    "in": "India",
    "us": "USA",
    "gb": "UK",
    "ca": "Canada",
    "au": "Australia",
    "nz": "New Zealand",
    "mx": "Mexico",
    "br": "Brazil",
    "de": "Germany",
    "fr": "France",
    "sg": "Singapore",
    "ae": "UAE",
    "za": "South Africa",
    "nl": "Netherlands",
    "es": "Spain",
    "it": "Italy",
    "ie": "Ireland",
    "pl": "Poland",
}


class AdzunaAdapter(SourceAdapter):
    name = "adzuna"

    def fetch(self, profile: Profile) -> list[RawJob]:
        app_id = secrets.get("ADZUNA_APP_ID")
        app_key = secrets.get("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            return []
        what = (profile.roles or profile.keywords or ["developer"])[0]
        if profile.remote and "remote" not in what.lower():
            what = f"{what} remote"
        country = profile.adzuna_country or "us"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 50,
            "what": what,
            "max_days_old": 7,
            "sort_by": "date",
        }
        out: list[RawJob] = []
        seen_ids: set = set()
        for page in range(1, profile.max_pages + 1):
            random_delay()
            with make_client() as client:
                resp = client.get(
                    f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}",
                    params=params,
                    headers={"Accept": "application/json"},
                )
                if blocked_response(resp):
                    raise BlockedError(f"{self.name}: blocked response (HTTP {resp.status_code})")
                try:
                    data = resp.json()
                except Exception:
                    break
            if not isinstance(data, dict):
                raise ParseFailureError(f"{self.name}: API returned non-object payload: {type(data).__name__}")
            results = data.get("results")
            if not isinstance(results, list):
                raise ParseFailureError(f"{self.name}: API payload missing 'results' list")
            if not results:
                break
            for r in results:
                if not isinstance(r, dict):
                    continue
                job_id = r.get("id") or ""
                if job_id and job_id in seen_ids:
                    continue
                if job_id:
                    seen_ids.add(job_id)
                title = r.get("title", "")
                company = (r.get("company") or {}).get("displayname", "")
                loc = (r.get("location") or {}).get("displayname", "")
                cname = COUNTRY_NAMES.get(country, country.upper())
                if cname.lower() not in loc.lower():
                    loc = f"{loc}, {cname}" if loc else cname
                desc = r.get("description", "")
                apply_url = r.get("redirect_url") or r.get("url") or ""
                created = r.get("created", "")
                out.append(
                    RawJob(
                        source_name=self.name,
                        source_url=apply_url or r.get("url", ""),
                        title=title,
                        company=company,
                        location=loc,
                        description=desc,
                        posted_date=created,
                        apply_url=apply_url,
                        extra={"salary": r.get("salary_min", ""), "contract_time": r.get("contract_time", "")},
                    )
                )
        return out
