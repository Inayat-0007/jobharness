from __future__ import annotations

from ...fetcher import make_client, random_delay
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter


class LeverAdapter(SourceAdapter):
    name = "lever"

    def fetch(self, profile: Profile) -> list[RawJob]:
        raw_boards = profile.lever_boards or [
            b for b in (getattr(profile, "company_allowlist", []) or []) if isinstance(b, str)
        ] or ["lever", "stripe"]
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
