from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from .algo import normalize_company, description_fingerprint as _description_fingerprint
from .scoring.thresholds import REQUIRED_JOB_FIELDS


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
    confidence_score: int = 0
    valid_through: str = ""
    employer_domain: str = ""
    missing_fields: list = field(default_factory=list)
    genuinely_new: bool = False
    seen_sources: list = field(default_factory=list)
    original_url: str = ""
    canonical_url: str = ""
    final_url: str = ""
    posting_id: str = ""
    canonical_job_id: str = ""
    block_key: list = field(default_factory=list)
    possible_duplicate_of: str = ""
    identity_score: float = 0.0
    authenticity_score: float = 0.0
    match_score: float = 0.0
    decision: str = ""
    matched_via: str = "exact"
    description_fingerprint: str = ""
    source_authority: int = 0
    job_version: int = 1
    evidence: list = field(default_factory=list)
    negative_evidence: list = field(default_factory=list)
    reason: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def compute_hash(self) -> str:
        self.job_id_hash = job_id_hash(self.title, self.company, self.location)
        return self.job_id_hash

    def compute_canonical_id(self) -> str:
        """Identity hierarchy, first non-empty wins:
        LEVEL 1 ATS/external posting ID
        LEVEL 2 canonical URL
        LEVEL 3 company entity + normalized title (location-agnostic)
        LEVEL 4 company + title + location
        LEVEL 5 fallback to job_id_hash (never empty)
        """
        if self.posting_id:
            return f"posting:{self.posting_id}"
        if self.canonical_url:
            return f"url:{self.canonical_url}"
        entity = normalize_company(self.company)
        if entity and self.title:
            return f"ct:{entity}|{_norm(self.title)}"
        if self.company and self.title and self.location:
            return f"ct:{_norm(self.company)}|{_norm(self.title)}|{_norm(self.location)}"
        if not self.job_id_hash:
            self.compute_hash()
        return f"hash:{self.job_id_hash}"

    def compute_fingerprint(self) -> str:
        self.description_fingerprint = _description_fingerprint(self.description)
        return self.description_fingerprint

    def mark_missing(self) -> None:
        missing = []
        for f in REQUIRED_JOB_FIELDS:
            v = getattr(self, f, "")
            if not v or v == MISSING:
                missing.append(f)
        self.missing_fields = missing


def _parse_date(date_posted):
    import datetime as _dt
    from email.utils import parsedate_to_datetime

    if date_posted is None:
        return None
    s = str(date_posted).strip()
    if not s or s == MISSING:
        return None
    # Epoch: pure-digit integers. 10 digits = seconds, 13 = milliseconds.
    if s.isdigit() and len(s) in (10, 13):
        try:
            v = float(s) if len(s) == 10 else float(s) / 1000.0
            return _dt.datetime.fromtimestamp(v, tz=_dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    # RFC-2822 / RSS pubDate, e.g. "Wed, 14 Nov 2023 10:00:00 GMT"
    try:
        r = parsedate_to_datetime(s)
        if r is not None:
            if r.tzinfo is None:
                r = r.replace(tzinfo=_dt.timezone.utc)
            return r
    except (TypeError, ValueError):
        pass
    # ISO-8601: trim trailing Z and fractional seconds before strptime
    iso = s.replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d %B %Y",
        "%B %d, %Y",
    ):
        try:
            r = _dt.datetime.strptime(iso, fmt)
            if r.tzinfo is None:
                r = r.replace(tzinfo=_dt.timezone.utc)
            return r
        except ValueError:
            continue
    return None


def freshness_label(date_posted: str) -> str:
    if not date_posted or date_posted == MISSING:
        return MISSING
    label = date_posted.strip().lower()
    now = time.time()
    parsed = _parse_date(date_posted)
    if parsed is None:
        for token, days in (("today", 0), ("just now", 0), ("hour", 0), ("day", 1), ("week", 7), ("month", 30)):
            if token in label:
                return "fresh" if days <= 1 else "recent"
        return MISSING
    age_days = (now - parsed.timestamp()) / 86400
    if age_days < 0:
        # future-dated -> treat as fresh
        return "fresh"
    if age_days <= 1:
        return "fresh"
    if age_days <= 7:
        return "recent"
    if age_days <= 30:
        return "older"
    return "stale"
