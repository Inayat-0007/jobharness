from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import asdict, dataclass, field
from email.utils import parsedate_to_datetime

from .algo import description_fingerprint as _description_fingerprint
from .algo import normalize_company
from .scoring.thresholds import REQUIRED_JOB_FIELDS


def _norm(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = text.replace("++", "pp")
    text = re.sub(r"(?<=[a-z0-9])#", "sharp", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return text.replace(" ", "")


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
    company: str | None = None
    location: str | None = None
    description: str | None = None
    posted_date: str | None = None
    apply_url: str | None = None
    raw_html: str | None = None
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
    re_alerted: bool = False                            # CLOSED->AUTHENTIC recovery re-alert flag
    _verify_ctx: dict | None = None                     # per-run verification context (internal)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_verify_ctx", None)
        return d

    def compute_hash(self) -> str:
        self.job_id_hash = job_id_hash(self.title, self.company, self.location)
        return self.job_id_hash

    def compute_canonical_id(self) -> str:
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


_RELATIVE_DATE_RE = re.compile(
    r"^(?:posted\s+)?"
    r"(?:(?P<word>today|yesterday)|"
    r"(?P<num>\d+)\s*(?P<unit>d|day|days|hour|hours|week|weeks|month|months)\s*ago)$",
    re.IGNORECASE,
)


def _parse_relative_date(s: str) -> _dt.datetime | None:
    m = _RELATIVE_DATE_RE.match(s.strip())
    if m is None:
        return None
    now = _dt.datetime.now(_dt.timezone.utc)
    today = now.date()
    if m.group("word"):
        days = 0 if m.group("word").lower() == "today" else 1
    else:
        n = min(int(m.group("num")), 365_000)
        unit = m.group("unit").lower()
        if unit == "d" or unit.startswith("day"):
            days = n
        elif unit.startswith("hour"):
            target = now - _dt.timedelta(hours=n)
            return _dt.datetime.combine(target.date(), _dt.time.min, tzinfo=_dt.timezone.utc)
        elif unit.startswith("week"):
            days = n * 7
        else:
            days = n * 30
    return _dt.datetime.combine(today - _dt.timedelta(days=days), _dt.time.min, tzinfo=_dt.timezone.utc)


def _parse_date(date_posted, date_format: str = "DMY"):
    if date_posted is None:
        return None
    s = str(date_posted).strip()
    if not s or s == MISSING:
        return None
    if s.isdigit() and len(s) in (10, 13):
        try:
            v = float(s) if len(s) == 10 else float(s) / 1000.0
            return _dt.datetime.fromtimestamp(v, tz=_dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    try:
        rel = _parse_relative_date(s)
    except (OverflowError, ValueError):
        rel = None
    if rel is not None:
        return rel
    try:
        r = parsedate_to_datetime(s)
        if r is not None:
            if r.tzinfo is None:
                r = r.replace(tzinfo=_dt.timezone.utc)
            return r
    except (TypeError, ValueError):
        pass
    iso = s.replace("Z", "+00:00")
    slash_first, slash_second = (
        ("%m/%d/%Y", "%d/%m/%Y") if str(date_format).upper() == "MDY" else ("%d/%m/%Y", "%m/%d/%Y")
    )
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        slash_first,
        slash_second,
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
    parsed = _parse_date(date_posted)
    if parsed is None:
        for token, days in (("today", 0), ("just now", 0), ("hour", 0), ("day", 1), ("week", 7), ("month", 30)):
            if token in label:
                return "fresh" if days <= 1 else "recent"
        return MISSING
    now = _dt.datetime.now(_dt.timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    age_days = max(0, (now.date() - parsed.date()).days)
    if age_days <= 1:
        return "fresh"
    if age_days <= 7:
        return "recent"
    if age_days <= 30:
        return "older"
    return "stale"
