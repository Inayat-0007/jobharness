from __future__ import annotations

from enum import Enum


class SourceStatus(Enum):
    """Per-source fetch outcome, recorded once per run and printed in the
    summary. OK is the happy path; the rest map to typed exceptions or empty
    results in the runner."""

    OK = "ok"
    EMPTY = "empty"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    SOURCE_DOWN = "source_down"
    PARSE_FAILURE = "parse_failure"
    NO_MATCH = "no_match"


# 5 = official ATS/API, 4 = employer career site, 3 = structured JobPosting,
# 2 = major aggregator, 1 = search/index, 0 = unknown.
SOURCE_AUTHORITY = {
    "greenhouse": 5,
    "lever": 5,
    "usajobs": 5,
    "adzuna": 5,
    "career_page_generic": 4,
    "career_page_browser": 4,
    "google_jobs": 3,
    "remoteok": 2,
    "weworkremotely": 2,
    "remotive": 2,
    "jobicy": 2,
    "linkedin": 0,
    "linkedin_guest": 2,
    "indeed": 0,
    "glassdoor": 0,
    "naukri": 0,
    "internshala": 0,
    "hirist": 0,
    "wellfound": 0,
}


def source_authority(source_name) -> int:
    return SOURCE_AUTHORITY.get(str(source_name or "").lower(), 1)
