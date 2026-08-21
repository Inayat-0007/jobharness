from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from jobharness.logging import get_logger

from ...fetcher import make_client, random_delay
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter
from ..exceptions import ParseFailureError

_LOG = get_logger(__name__)


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
        with ThreadPoolExecutor(max_workers=max(1, profile.career_fetch_workers)) as ex:
            futs = [ex.submit(self._fetch_board, board) for board in boards]
            for fut in futs:
                out.extend(fut.result())
        return out

    def _fetch_board(self, board: str) -> list[RawJob]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        random_delay()
        with make_client() as client:
            resp = client.get(url)
            if resp.status_code == 404:
                _LOG.warning("greenhouse board %r not found (404) - remove from profile", board)
                return []
            if resp.status_code != 200:
                return []
            try:
                data = resp.json()
            except Exception:
                return []
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
        out: list[RawJob] = []
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
