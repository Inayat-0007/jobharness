from __future__ import annotations

import feedparser

from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client


class RemotiveAdapter(SourceAdapter):
    name = "remotive"

    def fetch(self, profile: Profile) -> list[RawJob]:
        url = "https://remotive.com/remote-jobs/feed"
        out: list[RawJob] = []
        with make_client() as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return out
            parsed = feedparser.parse(resp.content)
        for entry in parsed.entries:
            title = entry.get("title", "")
            link = entry.get("link") or ""
            summary = entry.get("summary", "")
            posted = entry.get("published", "")
            company = ""
            if hasattr(entry, "tags") and entry.get("author"):
                company = entry.get("author", "")
            out.append(
                RawJob(
                    source_name=self.name,
                    source_url=link,
                    title=title,
                    company=company,
                    location="Remote",
                    description=summary,
                    posted_date=posted,
                    apply_url=link,
                )
            )
        return out
