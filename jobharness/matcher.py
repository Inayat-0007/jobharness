from __future__ import annotations

import re
import threading

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

_CACHE_LOCK = threading.Lock()

# Salary unit multipliers, annualized. All values are INR unless the text
# carries "$"/usd, in which case the raw numeric magnitude is kept and NOT
# currency-converted: for the India profile the floor is INR, so a "$100K"
# posting compares as 100,000 against the floor (documented limitation).
_SALARY_UNITS = {
    "lpa": 100_000.0, "lakh": 100_000.0, "lakhs": 100_000.0,
    "lac": 100_000.0, "lacs": 100_000.0,
    "cr": 10_000_000.0, "crore": 10_000_000.0, "crores": 10_000_000.0,
    "ctc": 1.0,  # CTC is an annual figure as stated
    "per annum": 1.0, "per year": 1.0, "annum": 1.0, "annual": 1.0,
    "yearly": 1.0, "pa": 1.0, "p.a.": 1.0, "/yr": 1.0, "/year": 1.0,
    "per month": 12.0, "monthly": 12.0, "a month": 12.0, "/month": 12.0,
    "per hour": 2000.0, "hourly": 2000.0, "per hr": 2000.0, "/hr": 2000.0,
    "k": 1000.0,
}
_SALARY_NUM_RE = re.compile(
    r"(?P<cur>\$|usd|₹|inr|rs\.?)?\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>lakhs\b|lakh\b|lacs\b|lac\b|crores\b|crore\b|"
    r"per annum\b|per year\b|per month\b|per hour\b|per hr\b|hourly\b|"
    r"monthly\b|yearly\b|annum\b|annual\b|a month\b|a year\b|"
    r"lpa\b|cr\b|ctc\b|pa\b|p\.a\.(?!\w)|/yr\b|/year\b|/month\b|/hr\b|k\b)?",
    re.IGNORECASE,
)


def _normalize_salary_to_annual(text) -> float | None:
    """Annualize every number+unit pair in a salary string; return the MAX.

    Multipliers: LPA/lakh/lac x100,000; crore x10,000,000; CTC and
    per-annum forms x1; per-month forms x12; per-hour forms x2000 (work
    hours per year); K x1,000. Bare numbers >= 1000 are treated as raw
    annual INR figures (small bare numbers are experience years/counts and
    are ignored). Returns None when no salary figure is present.
    """
    if not text:
        return None
    t = str(text).strip()
    if not t or t.upper() == "MISSING":
        return None
    found: list[float] = []
    for m in _SALARY_NUM_RE.finditer(t.lower()):
        num = float(m.group("num").replace(",", ""))
        unit = (m.group("unit") or "").strip()
        if unit:
            mult = _SALARY_UNITS.get(unit)
            if mult is None:
                continue
            found.append(num * mult)
        elif num >= 1000.0:
            found.append(num)
    return max(found) if found else None


def _compile_terms(terms: list[str]) -> list[re.Pattern]:
    """Compile word-bounded terms. Terms ending in non-word chars (c++, c#,
    p.a.) cannot use a trailing \\b (there is no boundary between two
    non-word chars), so the tail is a lookahead: end-of-string, a digit, or
    any non-alphanumeric character."""
    return [
        re.compile(r"\b" + re.escape(term.lower()) + r"(?=\d|[^a-z0-9]|$)")
        for term in terms
        if term
    ]


def _matches_patterns(text: str, patterns: list[re.Pattern]) -> bool:
    if not patterns:
        return False
    t = text.lower()
    return any(p.search(t) for p in patterns)


def _compiled_patterns(profile: Profile) -> dict:
    """Per-profile compiled role/keyword/exclude regexes, built lazily once.

    Profile instances are shared across the runner's worker threads, so the
    double-checked build is guarded by a module lock."""
    cached = getattr(profile, "_compiled_patterns", None)
    if cached is None:
        with _CACHE_LOCK:
            cached = getattr(profile, "_compiled_patterns", None)
            if cached is None:
                cached = {
                    "roles": _compile_terms(profile.roles),
                    "keywords": _compile_terms(profile.keywords),
                    "excludes": _compile_terms(profile.excludes),
                }
                profile._compiled_patterns = cached
    return cached


def _company_allowlist(profile: Profile) -> set[str]:
    """Profile-invariant allowlist set, built lazily once and cached on the profile."""
    cached = getattr(profile, "_allowed_companies", None)
    if cached is None:
        with _CACHE_LOCK:
            cached = getattr(profile, "_allowed_companies", None)
            if cached is None:
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
                profile._allowed_companies = allowed
                cached = allowed
    return cached


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

    patterns = _compiled_patterns(profile)

    # Excludes: any exclude term present -> reject
    if profile.excludes and _matches_patterns(haystack, patterns["excludes"]):
        return False

    # Roles: at least one role should appear in title/role/description (phrase match)
    if profile.roles:
        if not _matches_patterns(haystack, patterns["roles"]):
            return False

    # Keywords: ANY keyword present (OR). Empty keywords = no keyword filter.
    # An empty description must NOT bypass the filter: the keywords OR-gate is
    # then tested against title+company only, and a posting whose title+company
    # contains neither a keyword nor a role phrase is rejected.
    if profile.keywords:
        haystack_full = haystack + " " + " ".join(job.tech_stack_keywords).lower()
        if not _matches_patterns(haystack_full, patterns["keywords"]):
            if (job.description or "").strip():
                return False
            title_company = f"{job.title} {job.role} {job.company}".lower()
            if not _matches_patterns(title_company, patterns["keywords"]) and not _matches_patterns(
                title_company, patterns["roles"]
            ):
                return False

    # Seniority
    if profile.seniority and job.seniority:
        if profile.seniority.lower() not in job.seniority.lower():
            return False

    # Salary floor, two-sided: salary present => its annualized max must be
    # >= floor; salary text absent (or unparseable) passes (cannot judge).
    if profile.salary_floor:
        if job.salary_if_present and str(job.salary_if_present) != "MISSING":
            annual = _normalize_salary_to_annual(str(job.salary_if_present))
            if annual is not None and annual < int(profile.salary_floor):
                return False

    # Company allowlist enforcement (career-page-style sources only).
    # Allowed tokens come from greenhouse_boards / lever_boards (slugs, which the
    # adapters derive the company name from) and career_pages ({company,url}).
    if profile.company_allowlist or profile.greenhouse_boards or profile.lever_boards or profile.career_pages:
        if job.source_name in ("greenhouse", "lever", "career_page_generic", "career_page_browser"):
            allowed = _company_allowlist(profile)
            if allowed and not _company_allowed(job.company, allowed):
                return False

    return True
