from __future__ import annotations

import re

from .models import RawJob, Job, MISSING, VALID_AUTHENTIC, _parse_date
from .llm import provider as llm


EXTRACT_SCHEMA = (
    '{"role": str, "title": str, "company": str, "location": str, "experience_needed": str, '
    '"date_posted": str, "salary_if_present": str, "seniority": str, "tech_stack_keywords": list[str]}'
)


def make_extract_prompt(raw: RawJob) -> str:
    desc = (raw.description or "")[:4000]
    return (
        f"Extract the following fields from this job posting source text. "
        f"Return ONLY JSON matching this schema: {EXTRACT_SCHEMA}\n"
        f"For every field whose value is NOT explicitly stated in the source text, "
        f"use the exact string 'MISSING'. Do not guess or infer.\n\n"
        f"--- SOURCE ---\n"
        f"Title: {raw.title}\n"
        f"Company: {raw.company or MISSING}\n"
        f"Location: {raw.location or MISSING}\n"
        f"Posted date: {raw.posted_date or MISSING}\n"
        f"Description:\n{desc}\n"
        f"--- END SOURCE ---"
    )


def _is_missing(v) -> bool:
    return not v or v == MISSING or v == "MISSING"


def _coerce_keywords(v) -> list:
    if isinstance(v, list):
        return [str(x) for x in v if x and str(x) != MISSING]
    if isinstance(v, str) and not _is_missing(v):
        return [t.strip() for t in re.split(r"[,;/]", v) if t.strip()]
    return []


def normalize_date(raw: str | int | None) -> str:
    """Return a normalized 'YYYY-MM-DD' string, or '' if unparseable/missing.

    Handles epoch seconds (10 digits) / milliseconds (13 digits), RFC-2822,
    ISO-8601 (with Z / offset / fractional), and plain dates via models._parse_date.
    Never invents a date.
    """
    if raw is None:
        return ""
    parsed = _parse_date(str(raw))
    return parsed.strftime("%Y-%m-%d") if parsed is not None else ""


def extract(raw: RawJob, use_llm: bool = True, llm_provider: str = "gemini") -> Job:
    """Build a Job from a RawJob. LLM is optional and used only to refine fields."""
    job = Job(
        title=raw.title or "",
        company=raw.company or "",
        location=raw.location or "",
        remote="remote" in (raw.location or "").lower() or "remote" in (raw.description or "").lower(),
        apply_url_direct=raw.apply_url or "",
        source_url=raw.source_url,
        source_name=raw.source_name,
        posted_at=raw.posted_date or "",
        date_posted=normalize_date(raw.posted_date),
        description=raw.description or "",
    )
    extra = raw.extra or {}

    if use_llm:
        try:
            content = llm.complete(
                make_extract_prompt(raw), schema_hint=EXTRACT_SCHEMA, provider=llm_provider
            )
            fields = llm.extract_json(content)
        except Exception:
            fields = {}
        if fields:
            if not _is_missing(fields.get("role")):
                job.role = fields["role"]
            if not _is_missing(fields.get("title")):
                job.title = fields["title"]
            if not _is_missing(fields.get("company")):
                job.company = fields["company"]
            if not _is_missing(fields.get("location")):
                job.location = fields["location"]
            if not _is_missing(fields.get("experience_needed")):
                job.experience_needed = fields["experience_needed"]
            if not _is_missing(fields.get("date_posted")):
                job.date_posted = normalize_date(fields["date_posted"])
            if not _is_missing(fields.get("salary_if_present")):
                job.salary_if_present = fields["salary_if_present"]
            if not _is_missing(fields.get("seniority")):
                job.seniority = fields["seniority"]
            job.tech_stack_keywords = _coerce_keywords(fields.get("tech_stack_keywords"))

    # Non-LLM fallbacks from extra fields / raw text
    if not job.role and raw.title:
        job.role = raw.title
    if not job.experience_needed:
        exp = extra.get("experience_needed") or _infer_experience(raw.description or "")
        if exp:
            job.experience_needed = exp
    if not job.salary_if_present and extra.get("salary"):
        job.salary_if_present = str(extra.get("salary"))
    if extra.get("seniority"):
        job.seniority = str(extra.get("seniority"))
    if extra.get("valid_through"):
        job.valid_through = str(extra.get("valid_through"))
    if extra.get("remote") and not job.remote:
        job.remote = True

    job.compute_hash()
    job.mark_missing()
    if not job.date_posted:
        job.date_posted = normalize_date(raw.posted_date)
    from .models import freshness_label

    job.freshness = freshness_label(job.date_posted)
    return job


def _infer_experience(desc: str) -> str:
    if not desc:
        return ""
    d = desc.lower()
    if "5+ year" in d or "5 years" in d:
        return "5+ years"
    if "3+ year" in d or "3 years" in d:
        return "3+ years"
    if "2+ year" in d or "2 years" in d:
        return "2+ years"
    if "1+ year" in d or "1 year" in d:
        return "1+ year"
    return ""
