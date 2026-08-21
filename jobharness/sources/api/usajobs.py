from __future__ import annotations

from ... import secrets
from ...fetcher import blocked_response, make_client, random_delay
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter
from ..exceptions import BlockedError, ParseFailureError


class USAJobsAdapter(SourceAdapter):
    name = "usajobs"

    def fetch(self, profile: Profile) -> list[RawJob]:
        api_key = secrets.get("USAJOBS_API_KEY")
        if not api_key:
            return []
        what = " ".join(profile.roles[:1] + profile.keywords[:2]) or "Software Engineer"
        url = "https://www.usajobs.gov/api/search"
        headers = {
            "Host": "www.usajobs.gov",
            "User-Agent": "jobharness/0.1",
            "Authorization-Key": api_key,
        }
        out: list[RawJob] = []
        for page in range(1, profile.max_pages + 1):
            params: dict[str, str | int] = {"Keyword": what, "ResultsPerPage": 50, "SortField": "date", "Page": page}
            if profile.remote:
                params["RemoteIndicator"] = "true"
            random_delay()
            with make_client() as client:
                resp = client.get(url, params=params, headers=headers)
                if blocked_response(resp):
                    raise BlockedError(f"{self.name}: blocked response (HTTP {resp.status_code})")
                try:
                    data = resp.json()
                except Exception:
                    break
            if not isinstance(data, dict):
                raise ParseFailureError(f"{self.name}: API returned non-object payload: {type(data).__name__}")
            search_result = data.get("SearchResult")
            if not isinstance(search_result, dict) or not isinstance(search_result.get("SearchResultItems"), list):
                raise ParseFailureError(
                    f"{self.name}: API payload missing 'SearchResult.SearchResultItems' list"
                )
            items = search_result.get("SearchResultItems", [])
            if not items:
                break
            for item in items:
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
