from __future__ import annotations

import re

import feedparser

from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...fetcher import make_client


WWR_CATEGORIES = {
    "engineering": "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "fullstack": "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "front-end": "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "devops": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
}


def _parse_company_title(entry_title: str):
    # WWR titles look like "Company: Role"
    parts = entry_title.split(":", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", entry_title.strip()


WWWWW_COMPANY_RE = re.compile(r"Company:\s*(.+?)\s*</?a>", re.IGNORECASE)


class WeWorkRemotelyAdapter(SourceAdapter):
    name = "weworkremotely"

    def fetch(self, profile: Profile) -> list[RawJob]:
        out: list[RawJob] = []
        for cat, feed_url in WWR_CATEGORIES.items():
            with make_client() as client:
                resp = client.get(feed_url)
                if resp.status_code != 200:
                    continue
                parsed = feedparser.parse(resp.content)
            for entry in parsed.entries:
                title_raw = entry.get("title", "")
                company, title = _parse_company_title(title_raw)
                link = entry.get("link") or entry.get("id") or ""
                summary = entry.get("summary", "")
                posted = entry.get("published", "")
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
                        extra={"category": cat},
                    )
                )
        return out
