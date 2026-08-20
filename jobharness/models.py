from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return text


def job_id_hash(title: str, company: str, location: str = "") -> str:
    raw = f"{_norm(title)}|{_norm(company)}|{_norm(location)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


VALID_AUTHENTIC = "AUTHENTIC"
CLOSED = "CLOSED"
BLOCKED = "BLOCKED"
MISSING = "MISSING"


@dataclass
class RawJob:
    source_name: str
    source_url: str
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    posted_date: Optional[str] = None
    apply_url: Optional[str] = None
    raw_html: Optional[str] = None
    extra: dict = field(default_factory=dict)


@dataclass
class Job:
    role: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    remote: bool = False
    experience_needed: str = ""
    date_posted: str = ""
    freshness: str = ""
    salary_if_present: str = ""
    seniority: str = ""
    tech_stack_keywords: list = field(default_factory=list)
    description: str = ""
    apply_url_direct: str = ""
    source_url: str = ""
    source_name: str = ""
    posted_at: str = ""
    first_seen_at: float = 0.0
    job_id_hash: str = ""
    authentic_status: str = VALID_AUTHENTIC
    missing_fields: list = field(default_factory=list)
    genuinely_new: bool = False
    seen_sources: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def compute_hash(self) -> str:
        self.job_id_hash = job_id_hash(self.title, self.company, self.location)
        return self.job_id_hash

    def mark_missing(self) -> None:
        missing = []
        for f in ("title", "company", "apply_url_direct", "date_posted"):
            v = getattr(self, f, "")
            if not v or v == MISSING:
                missing.append(f)
        self.missing_fields = missing


def freshness_label(date_posted: str) -> str:
    if not date_posted:
        return MISSING
    label = date_posted.strip().lower()
    now = time.time()
    import datetime as _dt

    parsed: Optional[_dt.datetime] = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%d/%m/%Y"):
        try:
            parsed = _dt.datetime.strptime(date_posted[: len(_dt.datetime.now().strftime(fmt))], fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        for token, days in (("today", 0), ("just now", 0), ("hour", 0), ("day", 1), ("week", 7), ("month", 30)):
            if token in label:
                return "fresh" if days <= 1 else "recent"
        return MISSING
    age_days = (now - parsed.timestamp()) / 86400
    if age_days <= 1:
        return "fresh"
    if age_days <= 7:
        return "recent"
    if age_days <= 30:
        return "older"
    return "stale"
