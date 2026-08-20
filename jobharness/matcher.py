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

    # Company allowlist (if set and this source is career-page style)
    if profile.company_allowlist:
        allowed = [
            (c.lower() if isinstance(c, str) else c.get("company", "").lower())
            for c in profile.company_allowlist
        ]
        allowed = [a for a in allowed if a]
        # only enforce for company-specific career sources; for aggregators skip
        if job.source_name in ("greenhouse", "lever", "career_page_generic") and allowed:
            if job.company.lower() not in allowed and not any(a in job.company.lower() for a in allowed):
                return False

    return True
