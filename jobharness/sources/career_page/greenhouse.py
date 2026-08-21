from __future__ import annotations

from ..base import SourceAdapter
from ..exceptions import ParseFailureError
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client, random_delay


class GreenhouseAdapter(SourceAdapter):
    name = "greenhouse"

    def fetch(self, profile: Profile) -> list[RawJob]:
        raw_boards = profile.greenhouse_boards or [
            b for b in (getattr(profile, "company_allowlist", []) or []) if isinstance(b, str)
        ] or ["airbnb", "stripe"]
        boards = []
        for b in raw_boards:
            if isinstance(b, dict):
                slug = b.get("board") or b.get("slug") or b.get("company", "")
                if slug:
                    boards.append(str(slug))
            elif isinstance(b, str):
                boards.append(b)
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
                if not isinstance(data, dict):
                    raise ParseFailureError(
                        f"{self.name}: board {board} returned non-object payload: {type(data).__name__}"
                    )
            company = board.replace("-", " ").title()
            deps = data.get("departments") or []
            dep_lookup = (
                {d["id"]: d["name"] for d in deps if isinstance(d, dict)}
                if isinstance(deps, list)
                else {}
            )
            for job in data.get("jobs", []):
                if not isinstance(job, dict):
                    continue
                title = job.get("title", "")
                abs_url = job.get("absolute_url", "")
                loc = job.get("location", {}).get("name", "") if isinstance(job.get("location"), dict) else ""
                if not loc:
                    loc = ", ".join(j.get("name", "") for j in job.get("offices", []) if j.get("name"))
                departments = []
                for d in job.get("departments", []):
                    if isinstance(d, dict):
                        departments.append(d.get("name", dep_lookup.get(d.get("id"), "")))
                    elif isinstance(d, int):
                        departments.append(dep_lookup.get(d, ""))
                    elif isinstance(d, str):
                        departments.append(d)
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
