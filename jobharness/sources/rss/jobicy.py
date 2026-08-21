from __future__ import annotations

import feedparser

from ...fetcher import make_client
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter


class JobicyAdapter(SourceAdapter):
    name = "jobicy"

    def fetch(self, profile: Profile) -> list[RawJob]:
        url = "https://jobicy.com/feed"
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
