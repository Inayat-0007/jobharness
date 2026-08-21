from __future__ import annotations

import re

import feedparser

from ...fetcher import make_client
from ...models import RawJob
from ...profile import Profile
from ..base import SourceAdapter

_COMPANY_TITLE_RE = re.compile(r"^(?P<company>.+?)\s*[-\u2013]\s*(?P<title>.+)$")


def _company_from_title(title: str) -> str:
    if not title:
        return ""
    m = _COMPANY_TITLE_RE.match(title.strip())
    return (m.group("company") or "").strip() if m else ""


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
            company = (entry.get("author") or "").strip()
            if not company:
                company = _company_from_title(title)
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
