from __future__ import annotations

import re

from .models import Job
from .profile import Profile

# Cities/states whose presence in a location string marks it as India even when
# the word "India" is absent (e.g. "Bangalore, Karnataka").
INDIA_HINTS = (
    "india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "chennai",
    "delhi", "gurgaon", "gurugram", "noida", "kolkata", "jaipur", "ahmedabad",
    "kochi", "cochin", "trivandrum", "thiruvananthapuram", "lucknow", "kanpur",
    "indore", "bhopal", "nagpur", "surat", "rajkot", "goa", "chandigarh",
    "dehradun", "guwahati", "bhubaneswar", "amritsar", "vadodara", "nashik",
    "coimbatore", "madurai", "mysore", "mysuru", "visakhapatnam", "vijayawada",
    "gwalior", "jodhpur", "karnataka", "maharashtra", "tamil nadu", "telangana",
    "uttar pradesh", "rajasthan", "gujarat", "odisha", "kerala", "west bengal",
    "punjab", "haryana", "andhra pradesh", "madhya pradesh", "himachal",
    "assam", "bihar", "jharkhand", "uttarakhand", "chhattisgarh", "sikkim",
    "arunachal", "puducherry", "pondicherry", "ladakh", "kashmir",
)
REMOTE_WORDS = ("remote", "anywhere", "worldwide", "global", "telecommute", "work from home", "virtual")


def _matches_any(text: str, terms: list[str]) -> bool:
    if not terms:
        return False
    t = text.lower()
    return any(re.search(r"\b" + re.escape(term.lower()) + r"\b", t) for term in terms if term)


def _company_allowed(company: str, allowed: set[str]) -> bool:
    """Word-boundary match of allowlist tokens against the company name.

    Substring matching falsely admitted e.g. 'airbnbish' for 'airbnb'; tokens
    must match a whole word of the company name ('Airbnb Inc.' -> 'airbnb')."""
    if not allowed or not company:
        return False
    c = company.lower()
    if c in allowed:
        return True
    return any(t in allowed for t in re.findall(r"[a-z0-9]+", c))


def matches_profile(job: Job, profile: Profile) -> bool:
    """Apply title/keyword/exclude/seniority/salary/location filters. Pure-source-derived only."""
    haystack = f"{job.title} {job.role} {job.description if hasattr(job,'description') else ''}".lower()

    # Location: profile.location set => job must be located in that region.
    # Strict mode: when profile.remote is false, remote/anywhere jobs are
    # REJECTED (India on-site only). Foreign on-site locations are rejected.
    # Indian city/state names count as India even without the word "India".
    # Empty/unknown locations are allowed (cannot classify, never assumed remote).
    if profile.location:
        loc = (job.location or "").lower()
        term = profile.location.lower()
        if loc:
            remoteish = any(w in loc for w in REMOTE_WORDS)
            if remoteish:
                return profile.remote
            hints = INDIA_HINTS if "india" in term else (term,)
            if not any(h in loc for h in hints):
                return False

    # Excludes: any exclude term present -> reject
    if profile.excludes and _matches_any(haystack, profile.excludes):
        return False

    # Roles: at least one role should appear in title/role/description (phrase match)
    if profile.roles:
        if not _matches_any(haystack, profile.roles):
            return False

    # Keywords: ANY keyword present (OR). Empty keywords = no keyword filter.
    # If the description could not be fetched (empty), skip the keyword check
    # - the role + location + exclude filters already gate quality, and a
    # missing description never means the job is a poor match.
    if profile.keywords:
        haystack_full = haystack + " " + " ".join(job.tech_stack_keywords).lower()
        if not _matches_any(haystack_full, profile.keywords):
            if (job.description or "").strip():
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
        if job.source_name in ("greenhouse", "lever", "career_page_generic", "career_page_browser"):
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
            if allowed and not _company_allowed(job.company, allowed):
                return False

    return True
