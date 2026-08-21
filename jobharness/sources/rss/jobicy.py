from __future__ import annotations

from ...fetcher import blocked_response, make_client
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter
from ..exceptions import BlockedError, ParseFailureError


class JobicyAdapter(SourceAdapter):
    name = "jobicy"

    def fetch(self, profile: Profile) -> list[RawJob]:
        # Jobicy's RSS feeds are gone (403/404 as of 2026-08); the public v2
        # JSON API is the canonical endpoint. `count` is its only supported
        # query param - it has no page/offset parameter, so pagination is not
        # applicable and profile.max_pages does not drive anything here.
        url = "https://jobicy.com/api/v2/remote-jobs"
        params = {"count": 50}
        out: list[RawJob] = []
        with make_client() as client:
            resp = client.get(url, params=params, headers={"Accept": "application/json"})
            if blocked_response(resp):
                raise BlockedError(f"{self.name}: blocked response (HTTP {resp.status_code})")
            if resp.status_code != 200:
                return out
            try:
                data = resp.json()
            except Exception:
                return out
        if not isinstance(data, dict):
            raise ParseFailureError(f"{self.name}: API returned non-object payload: {type(data).__name__}")
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise ParseFailureError(f"{self.name}: API payload missing 'jobs' list")
        for j in jobs:
            if not isinstance(j, dict):
                continue
            link = j.get("url") or ""
            out.append(
                RawJob(
                    source_name=self.name,
                    source_url=link,
                    title=j.get("jobTitle", ""),
                    company=j.get("companyName", ""),
                    location=j.get("jobGeo") or "Remote",
                    description=j.get("jobExcerpt", ""),
                    posted_date=j.get("pubDate", ""),
                    apply_url=link,
                    extra={
                        "salary_min": j.get("salaryMin", ""),
                        "salary_max": j.get("salaryMax", ""),
                        "salary_currency": j.get("salaryCurrency", ""),
                        "salary_period": j.get("salaryPeriod", ""),
                        "job_type": ", ".join(j.get("jobType") or []),
                    },
                )
            )
        return out
