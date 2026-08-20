from __future__ import annotations

from ... import secrets
from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client, blocked_response, random_delay


class AdzunaAdapter(SourceAdapter):
    name = "adzuna"

    def fetch(self, profile: Profile) -> list[RawJob]:
        app_id = secrets.get("ADZUNA_APP_ID")
        app_key = secrets.get("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            return []
        what = " ".join(profile.roles[:1] + profile.keywords[:3]) or "developer"
        if profile.remote and "remote" not in what.lower():
            what = what + " remote"
        country = "us"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 50,
            "what": what,
            "max_days_old": 7,
            "sort_by": "date",
        }
        random_delay()
        out: list[RawJob] = []
        with make_client() as client:
            resp = client.get(
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                params=params,
            )
            if blocked_response(resp):
                return out
            try:
                data = resp.json()
            except Exception:
                return out
        for r in data.get("results", []):
            title = r.get("title", "")
            company = (r.get("company") or {}).get("displayname", "")
            loc = (r.get("location") or {}).get("displayname", "")
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
