from __future__ import annotations

from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client, random_delay


class LeverAdapter(SourceAdapter):
    name = "lever"

    def fetch(self, profile: Profile) -> list[RawJob]:
        boards = profile.company_allowlist or ["lever", "stripe"]
        out: list[RawJob] = []
        for board in boards:
            board = board.strip()
            if not board:
                continue
            url = f"https://api.lever.co/v0/postings/{board}?mode=json"
            random_delay()
            with make_client() as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    continue
                try:
                    postings = resp.json()
                except Exception:
                    continue
            company = board.replace("-", " ").title()
            for p in postings:
                if not isinstance(p, dict):
                    continue
                title = p.get("text", "")
                apply_url = p.get("hostedUrl") or ""
                loc = ""
                if isinstance(p.get("categories"), dict):
                    loc = p.get("categories", {}).get("location", "")
                desc = p.get("description", {}).get("plain", "") if isinstance(p.get("description"), dict) else ""
                out.append(
                    RawJob(
                        source_name=self.name,
                        source_url=apply_url,
                        title=title,
                        company=company,
                        location=loc or "Remote",
                        description=desc,
                        posted_date=p.get("createdAt", ""),
                        apply_url=apply_url,
                        extra={"job_id": p.get("id", ""), "commitment": (p.get("categories") or {}).get("commitment", "")},
                    )
                )
        return out
