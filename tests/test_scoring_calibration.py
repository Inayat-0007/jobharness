"""Scoring calibration regression tests (2026-08 fix).

Live evidence from 4 production runs (183+ matched jobs): the old
normalization made AUTO_ACCEPT structurally unreachable (max match_score
0.230 vs AUTO_ACCEPT_MATCH 0.60; max authenticity 63.3 vs 70; 100% REVIEW,
0 AUTO_ACCEPT). These tests pin the recalibrated behavior:

- bm25_coverage and skill_overlap saturate at ~8 matched terms/keywords
  instead of being diluted by the full profile size (74 query tokens /
  47 keywords in production).
- AUTO_ACCEPT_MATCH 0.30 / AUTO_ACCEPT_AUTHENTICITY 55 are reachable for a
  realistic employer-ATS (greenhouse) job but NOT for a typical portal
  (linkedin_guest) job, whose authenticity ceiling is ~43-48.
"""

from __future__ import annotations

from jobharness.models import Job
from jobharness.profile import Profile
from jobharness.scoring.authenticity import authenticity_score
from jobharness.scoring.decision import decide
from jobharness.scoring.matching import bm25_coverage, score_match, skill_overlap
from jobharness.scoring.thresholds import (
    AUTO_ACCEPT,
    AUTO_ACCEPT_AUTHENTICITY,
    AUTO_ACCEPT_MATCH,
    MEDIUM_AUTHENTICITY,
    REJECT,
    REVIEW,
    REVIEW_MATCH,
    STATE_OPEN,
)

# Production-scale profile shape (33 roles + 47 keywords in the live config);
# a representative subset is enough — what matters is >8 query tokens/keywords
# so saturation caps, not profile size, drive the score.
ROLES = [
    "Software Engineer Fresher", "Backend Engineer", "Python Developer",
    "Full Stack Developer", "Software Development Engineer",
    "Junior Software Engineer", "Entry Level Software Engineer",
    "Cloud Engineer", "DevOps Engineer", "Data Engineer",
    "Associate Software Engineer", "Graduate Engineer Trainee",
]

KEYWORDS = [
    "python", "java", "javascript", "typescript", "react", "nodejs", "django",
    "flask", "aws", "azure", "gcp", "docker", "kubernetes", "git",
    "sql", "mysql", "postgresql", "mongodb", "api", "rest",
    "microservices", "linux", "agile", "testing", "data structures",
    "algorithms", "ci cd", "terraform",
]


def india_profile(**kw):
    p = Profile(roles=ROLES, keywords=KEYWORDS, excludes=[], location="India",
                remote=False, seniority="fresher")
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def linkedin_fresher_job():
    # Portal-sourced (linkedin_guest, authority=2): apply host is linkedin.com,
    # never the employer domain, so employer_domain stays empty -> domain_match=0.
    return Job(
        role="Software Engineer - Fresher",
        title="Software Engineer - Fresher",
        company="Amazon",
        location="Bengaluru, India",
        remote=False,
        experience_needed="0-1 years",
        date_posted="2026-08-20",
        freshness="recent",
        seniority="fresher",
        description="You will build api services in python and deploy on aws.",
        apply_url_direct="https://www.linkedin.com/jobs/view/1234567890",
        source_name="linkedin_guest",
        source_authority=2,
        posting_id="1234567890",
        authentic_status="AUTHENTIC",
        employer_domain="",
    )


def greenhouse_job():
    # Employer-ATS sourced (authority=5), employer-domain identity known,
    # complete fields, future validThrough: the realistic AUTO_ACCEPT path.
    return Job(
        role="Software Engineer",
        title="Software Engineer",
        company="Acme",
        location="Remote",
        remote=True,
        experience_needed="0-1 years",
        date_posted="2026-08-21",
        freshness="fresh",
        seniority="fresher",
        description=("Acme is hiring a Software Engineer. Build python backend "
                     "api services, deploy on aws with docker and kubernetes, "
                     "work with sql, git, rest and microservices in an agile team."),
        apply_url_direct="https://boards.greenhouse.io/acme/jobs/456",
        source_name="greenhouse",
        source_authority=5,
        posting_id="gh-456",
        authentic_status="AUTHENTIC",
        employer_domain="acme.com",
        valid_through="2026-12-31",
    )


def weak_job():
    return Job(
        role="Senior Oracle DBA",
        title="Senior Oracle Database Administrator",
        company="LegacyCorp",
        location="New York",
        remote=False,
        experience_needed="10+ years",
        date_posted="2026-08-01",
        freshness="older",
        seniority="senior",
        description="Manage oracle databases, mainframe batch jobs and on-prem storage clusters.",
        apply_url_direct="https://legacycorp.example.com/jobs/9",
        source_name="career_page",
        source_authority=3,
        posting_id="9",
        authentic_status="AUTHENTIC",
        employer_domain="legacycorp.example.com",
    )


def test_bm25_coverage_saturates_at_cap_not_profile_size():
    # A 74-term production-sized query: matching 8 distinct terms saturates.
    query = [f"t{i}" for i in range(74)]
    assert bm25_coverage(query, query[:8]) == 1.0
    # Matching 4 of 74 terms scores 0.5 (old normalization: 4/74 ~= 0.054).
    assert bm25_coverage(query, query[:4]) == 0.5
    # Small queries still normalize by their own size.
    assert bm25_coverage(["a", "b", "c"], ["a", "b", "c"]) == 1.0


def test_skill_overlap_saturates_at_cap_not_profile_size():
    big = Profile(keywords=[f"skill{i}" for i in range(47)])
    four = Job(title="skill0 skill1 skill2 skill3", description="")
    assert skill_overlap(four, big) == 0.5  # old: 4/47 ~= 0.085
    eight = Job(title=" ".join(f"skill{i}" for i in range(10)), description="")
    assert skill_overlap(eight, big) == 1.0  # 8+ matched keywords saturate
    # Small profiles still normalize by their own keyword count.
    small = Profile(keywords=["python", "aws", "api"])
    full = Job(title="python aws api", description="")
    assert skill_overlap(full, small) == 1.0


def test_strong_linkedin_fresher_job_is_review_not_auto_accept():
    p = india_profile()
    j = linkedin_fresher_job()
    match = score_match(j, p)
    auth = authenticity_score(j)
    assert AUTO_ACCEPT_MATCH <= match <= 0.55  # strong portal match, ~0.30-0.55
    assert MEDIUM_AUTHENTICITY <= auth < AUTO_ACCEPT_AUTHENTICITY  # portal ceiling ~43-48
    d, reasons = decide(0.0, auth, match, STATE_OPEN)
    assert d == REVIEW
    assert "authenticity medium" in reasons


def test_saturated_match_exceeds_auto_accept_threshold():
    p = india_profile(location="", remote=True)
    j = greenhouse_job()
    match = score_match(j, p)
    assert match >= AUTO_ACCEPT_MATCH


def test_auto_accept_reachable_end_to_end_for_greenhouse_job():
    p = india_profile(location="", remote=True)
    j = greenhouse_job()
    match = score_match(j, p)
    auth = authenticity_score(j)
    assert auth >= AUTO_ACCEPT_AUTHENTICITY
    assert match >= AUTO_ACCEPT_MATCH
    # Both identity paths that pass the gate must AUTO_ACCEPT.
    d_known, reasons_known = decide(1.0, auth, match, STATE_OPEN)
    assert d_known == AUTO_ACCEPT
    assert "identity very high" in reasons_known
    d_new, reasons_new = decide(0.0, auth, match, STATE_OPEN)
    assert d_new == AUTO_ACCEPT
    assert "no known duplicates" in reasons_new


def test_weak_job_stays_below_review_and_rejects():
    p = india_profile(location="", remote=True)
    j = weak_job()
    match = score_match(j, p)
    auth = authenticity_score(j)
    assert match < REVIEW_MATCH  # no threshold collapse: weak jobs stay low
    d, reasons = decide(0.0, auth, match, STATE_OPEN)
    assert d in (REVIEW, REJECT)
    assert d != AUTO_ACCEPT
