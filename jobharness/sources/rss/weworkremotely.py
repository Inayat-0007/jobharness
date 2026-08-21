from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import feedparser

from ...fetcher import make_client
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter

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


class WeWorkRemotelyAdapter(SourceAdapter):
    name = "weworkremotely"

    def fetch(self, profile: Profile) -> list[RawJob]:
        # RSS feeds have no pagination; each category feed is one page.
        out: list[RawJob] = []
        with ThreadPoolExecutor(max_workers=max(1, profile.career_fetch_workers)) as ex:
            futs = [
                ex.submit(self._fetch_feed, cat, feed_url)
                for cat, feed_url in WWR_CATEGORIES.items()
            ]
            for fut in futs:
                out.extend(fut.result())
        return out

    def _fetch_feed(self, cat: str, feed_url: str) -> list[RawJob]:
        out: list[RawJob] = []
        with make_client() as client:
            resp = client.get(feed_url)
            if resp.status_code != 200:
                return out
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
