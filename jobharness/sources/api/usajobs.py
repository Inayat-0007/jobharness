from __future__ import annotations

from ... import secrets
from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client, blocked_response, random_delay


class USAJobsAdapter(SourceAdapter):
    name = "usajobs"

    def fetch(self, profile: Profile) -> list[RawJob]:
        api_key = secrets.get("USAJOBS_API_KEY")
        if not api_key:
            return []
        what = " ".join(profile.roles[:1] + profile.keywords[:2]) or "Software Engineer"
        url = "https://www.usajobs.gov/api/search"
        params = {"Keyword": what, "ResultsPerPage": 50, "SortField": "date"}
        if profile.remote:
            params["RemoteIndicator"] = "true"
        headers = {
            "Host": "www.usajobs.gov",
            "User-Agent": "jobharness/0.1",
            "Authorization-Key": api_key,
        }
        random_delay()
        out: list[RawJob] = []
        with make_client() as client:
            resp = client.get(url, params=params, headers=headers)
            if blocked_response(resp):
                return out
            try:
                data = resp.json()
            except Exception:
                return out
        for item in data.get("SearchResult", {}).get("SearchResultItems", []):
            jd = item.get("MatchedObjectDescriptor", {})
            title = jd.get("PositionTitle", "")
            company = jd.get("OrganizationName", "")
            loc = jd.get("PositionLocationDisplay", "")
            desc = jd.get("QualificationSummary", "")
            apply_uris = jd.get("ApplyURI")
            apply_url = (
                apply_uris[0]
                if isinstance(apply_uris, list) and apply_uris
                else apply_uris
                if isinstance(apply_uris, str)
                else ""
            )
            posted = jd.get("PublicationStartDate", "")
            out.append(
                RawJob(
                    source_name=self.name,
                    source_url=apply_url or "",
                    title=title,
                    company=company,
                    location=loc,
                    description=desc,
                    posted_date=posted,
                    apply_url=apply_url,
                    extra={
                        "salary_min": jd.get("PositionMinimumRemuneration", ""),
                        "salary_max": jd.get("PositionMaximumRemuneration", ""),
                        "pos_schedule": jd.get("PositionScheduleTypeCode", ""),
                    },
                )
            )
        return out
