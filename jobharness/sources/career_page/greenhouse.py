from __future__ import annotations

from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client, random_delay


class GreenhouseAdapter(SourceAdapter):
    name = "greenhouse"

    def fetch(self, profile: Profile) -> list[RawJob]:
        boards = profile.company_allowlist or ["airbnb", "stripe"]
        out: list[RawJob] = []
        for board in boards:
            url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
            random_delay()
            with make_client() as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    continue
                try:
                    data = resp.json()
                except Exception:
                    continue
            company = board.replace("-", " ").title()
            dep_lookup = {d["id"]: d["name"] for d in data.get("departments", [])}
            for job in data.get("jobs", []):
                title = job.get("title", "")
                abs_url = job.get("absolute_url", "")
                loc = job.get("location", {}).get("name", "") if isinstance(job.get("location"), dict) else ""
                if not loc:
                    loc = ", ".join(j.get("name", "") for j in job.get("offices", []) if j.get("name"))
                departments = [dep_lookup.get(i, "") for i in job.get("departments", [])]
                out.append(
                    RawJob(
                        source_name=self.name,
                        source_url=abs_url,
                        title=title,
                        company=company,
                        location=loc,
                        description=job.get("content", ""),
                        posted_date=job.get("updated_at", ""),
                        apply_url=f"https://boards.greenhouse.io/{board}#{job.get('id','')}",
                        extra={"departments": departments, "job_id": job.get("id", "")},
                    )
                )
        return out
