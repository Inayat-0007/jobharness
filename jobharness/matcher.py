from __future__ import annotations

import re

from .models import Job
from .profile import Profile


def _matches_any(text: str, terms: list[str]) -> bool:
    if not terms:
        return False
    t = text.lower()
    return any(re.search(r"\b" + re.escape(term.lower()) + r"\b", t) for term in terms if term)


def matches_profile(job: Job, profile: Profile) -> bool:
    """Apply title/keyword/exclude/seniority/salary filters. Pure-source-derived only."""
    haystack = f"{job.title} {job.role} {job.description if hasattr(job,'description') else ''}".lower()

    # Excludes: any exclude term present -> reject
    if profile.excludes and _matches_any(haystack, profile.excludes):
        return False

    # Roles: at least one role should appear in title/role/description (phrase match)
    if profile.roles:
        if not _matches_any(haystack, profile.roles):
            return False

    # Keywords: ANY keyword present (OR). Empty keywords = no keyword filter.
    if profile.keywords:
        haystack_full = haystack + " " + " ".join(job.tech_stack_keywords).lower()
        if not _matches_any(haystack_full, profile.keywords):
            return False

    # Seniority
    if profile.seniority and job.seniority:
        if profile.seniority.lower() not in job.seniority.lower():
            return False

    # Salary floor
    if profile.salary_floor:
        if job.salary_if_present and job.salary_if_present != "MISSING":
            nums = re.findall(r"(\d[\d,]*)", job.salary_if_present.replace(",", ""))
            if nums and max(int(n) for n in nums) < int(profile.salary_floor):
                return False

    # Company allowlist enforcement (career-page-style sources only).
    # Allowed tokens come from greenhouse_boards / lever_boards (slugs, which the
    # adapters derive the company name from) and career_pages ({company,url}).
    if profile.company_allowlist or profile.greenhouse_boards or profile.lever_boards or profile.career_pages:
        if job.source_name in ("greenhouse", "lever", "career_page_generic"):
            allowed = set()
            for b in profile.greenhouse_boards:
                allowed.add(str(b).lower())
            for b in profile.lever_boards:
                allowed.add(str(b).lower())
            for c in profile.career_pages:
                if isinstance(c, dict) and c.get("company"):
                    allowed.add(str(c["company"]).lower())
            for c in (getattr(profile, "company_allowlist", []) or []):  # legacy
                if isinstance(c, str):
                    allowed.add(c.lower())
                elif isinstance(c, dict) and c.get("company"):
                    allowed.add(str(c["company"]).lower())
            allowed.discard("")
            if allowed and job.company.lower() not in allowed and not any(a in job.company.lower() for a in allowed):
                return False

    return True
