from __future__ import annotations

import logging
import re

from .llm import provider as llm
from .models import MISSING, Job, RawJob, _parse_date

logger = logging.getLogger(__name__)


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


# Conservative tech terms matched word-bounded against the raw source text.
# Source-derived keywords are UNIONED with the LLM keyword list so a real
# source signal is never overwritten by an LLM that returned a short list.
_TECH_TERMS = (
    "python",
    "django",
    "flask",
    "fastapi",
    "javascript",
    "typescript",
    "react",
    "angular",
    "vue",
    "node",
    "nodejs",
    "java",
    "spring",
    "kotlin",
    "swift",
    "golang",
    "rust",
    "c++",
    "c#",
    "sql",
    "postgresql",
    "mysql",
    "mongodb",
    "redis",
    "kafka",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "terraform",
    "linux",
    "git",
    "machine learning",
    "data science",
    "pandas",
    "numpy",
    "tensorflow",
    "pytorch",
    "selenium",
    "tableau",
    "power bi",
)


def _source_tech_keywords(text) -> list[str]:
    """Curated tech terms present in the source text (word-boundary match)."""
    if not text:
        return []
    t = str(text).lower()
    return [term for term in _TECH_TERMS if re.search(r"\b" + re.escape(term) + r"\b", t)]


def _consistent(a, b) -> bool:
    """Groundedness gate for LLM-extracted values.

    True when value `a` is supported by source text `b`: `a` occurs in `b` as
    a case-insensitive substring, or >=80% of `a`'s tokens appear in `b`.
    A hallucinated value (e.g. a company name absent from the posting) fails
    both tests and is never adopted in place of source truth.
    """
    a = str(a or "").strip().lower()
    b = str(b or "").strip().lower()
    if not a or not b:
        return False
    if a in b:
        return True
    ta = [t for t in re.split(r"[^a-z0-9]+", a) if t]
    tb = set(t for t in re.split(r"[^a-z0-9]+", b) if t)
    if not ta:
        return False
    return sum(1 for t in ta if t in tb) / len(ta) >= 0.8


def _llm_source_text(raw: RawJob) -> str:
    """The full text the LLM was asked to extract from, plus posting metadata.

    This is the consistency-check corpus: the same truncated description the
    prompt saw, the raw title/company/location/date, both URLs, and every
    adapter-provided extra value. Raw HTML is excluded (the LLM never sees it).
    """
    parts = [
        raw.title,
        raw.company,
        raw.location,
        (raw.description or "")[:4000],
        raw.posted_date,
        raw.apply_url,
        raw.source_url,
    ]
    for v in (raw.extra or {}).values():
        if v is not None:
            parts.append(str(v))
    return " ".join(p for p in parts if p)


def normalize_date(raw: str | int | None, date_format: str = "DMY") -> str:
    """Return a normalized 'YYYY-MM-DD' string, or '' if unparseable/missing.

    Handles epoch seconds (10 digits) / milliseconds (13 digits), RFC-2822,
    ISO-8601 (with Z / offset / fractional), relative dates, and plain formats
    via models._parse_date.  Never invents a date.
    """
    if raw is None:
        return ""
    parsed = _parse_date(str(raw), date_format=date_format)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else ""


def extract(raw: RawJob, use_llm: bool = True, llm_provider: str = "gemini", date_format: str = "DMY") -> Job:
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
        date_posted=normalize_date(raw.posted_date, date_format=date_format),
        description=raw.description or "",
    )
    extra = raw.extra or {}

    if use_llm:
        try:
            content = llm.complete(
                make_extract_prompt(raw), schema_hint=EXTRACT_SCHEMA, provider=llm_provider
            )
            fields = llm.extract_json(content)
        except Exception as e:
            logger.warning("LLM extraction failed (provider=%s): %s", llm_provider, e)
            fields = {}
        if fields:
            src = _llm_source_text(raw)
            if not _is_missing(fields.get("role")):
                job.role = fields["role"]
            # Consistency gate: title/company/location are adopted ONLY when
            # grounded in the source text (substring or >=80% token overlap).
            # A hallucinated value never replaces source truth.
            for f in ("title", "company", "location"):
                v = fields.get(f)
                if not _is_missing(v) and _consistent(v, src):
                    setattr(job, f, str(v).strip())
            if not _is_missing(fields.get("experience_needed")):
                job.experience_needed = fields["experience_needed"]
            if not _is_missing(fields.get("date_posted")):
                llm_date = normalize_date(fields["date_posted"], date_format=date_format)
                if llm_date and (llm_date == job.date_posted or _consistent(fields["date_posted"], src)):
                    job.date_posted = llm_date
            if not _is_missing(fields.get("salary_if_present")):
                job.salary_if_present = fields["salary_if_present"]
            if not _is_missing(fields.get("seniority")):
                job.seniority = fields["seniority"]
            # Union, never overwrite: source-derived tech keywords survive an
            # LLM list that omitted them.
            llm_kws = _coerce_keywords(fields.get("tech_stack_keywords"))
            src_kws = _source_tech_keywords(src)
            job.tech_stack_keywords = llm_kws + [k for k in src_kws if k not in llm_kws]

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
        job.date_posted = normalize_date(raw.posted_date, date_format=date_format)
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
