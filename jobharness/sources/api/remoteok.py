from __future__ import annotations

from ...fetcher import blocked_response, make_client, random_delay
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter
from ..exceptions import BlockedError


class RemoteOKAdapter(SourceAdapter):
    name = "remoteok"

    def fetch(self, profile: Profile) -> list[RawJob]:
        url = "https://remoteok.com/api"
        random_delay()
        out: list[RawJob] = []
        with make_client() as client:
            resp = client.get(url, headers={"Accept": "application/json"})
            if blocked_response(resp):
                raise BlockedError(f"{self.name}: blocked response (HTTP {resp.status_code})")
            try:
                data = resp.json()
            except Exception:
                return out
        # First element is a metadata dict; rest are jobs
        jobs = [j for j in data if isinstance(j, dict) and "slug" in j]
        for j in jobs:
            title = j.get("position") or j.get("title") or ""
            company = j.get("company") or ""
            location = j.get("location") or ""
            tags = j.get("tags") or []
            apply_url = j.get("url") or ""
            if apply_url and not apply_url.startswith("http"):
                apply_url = "https://remoteok.com" + apply_url
            out.append(
                RawJob(
                    source_name=self.name,
                    source_url=apply_url,
                    title=title,
                    company=company,
                    location=location,
                    description=j.get("description", ""),
                    posted_date=j.get("date") or "",
                    apply_url=apply_url,
                    extra={"tags": tags, "salary": j.get("salary", ""), "logo": j.get("logo", "")},
                )
            )
        return out
