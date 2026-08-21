from __future__ import annotations

import time

import httpx

from . import algo
from .models import Job, CLOSED, MISSING, _parse_date, freshness_label
from .fetcher import make_client, blocked_response, resp_text
from .urlutil import apply_url_domain as _domain
from .scoring.authenticity import authenticity_score as _authenticity_score
from .scoring.thresholds import (
    REJECT as _REJECT_DECISION,
    SCORE_ATS_BOOST,
    SCORE_ATS_MIN_AUTHORITY,
    SCORE_BLOCKED_CAP,
    SCORE_CAP,
    SCORE_COMPLETENESS_WEIGHT,
    SCORE_DOMAIN_MATCH_BOOST,
    SCORE_DOMAIN_MATCH_CAP,
    SCORE_EXPIRED_PENALTY,
    SCORE_FRESH_BONUS,
    SCORE_OLDER_BONUS,
    SCORE_RECENT_BONUS,
    SCORE_STALE_PENALTY,
)
from .evidence.source import source_authority

_company_domain_hint = algo.company_domain_hint


CLOSED_MARKERS = (
    "no longer accepting",
    "this position has been closed",
    "job has been closed",
    "job has expired",
    "requisition has been closed",
    "this job posting is no longer active",
    "this requisition",
    "no longer open",
    "position has been filled",
    "we are no longer",
    "this listing has expired",
    "job is no longer",
)


def verify(job: Job, check_reachable: bool = True) -> Job:
    """Resolve apply_url, follow redirects, confirm not CLOSED, score confidence.

    Sets job.authentic_status = CLOSED (and decision = REJECT) if unreachable
    or a closed marker found. Computes job.confidence_score (0-100), sets
    employer_domain, and scores the apply URL host against the company name.
    """
    job.confidence_score = _score_base(job)
    job.authenticity_score = float(_authenticity_score(job))
    url = job.apply_url_direct
    if not url or url == MISSING:
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        return job
    # Stale via validThrough (no network needed) => mark CLOSED if in the past.
    if _is_expired(job.valid_through):
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        return job
    if not check_reachable:
        return job

    try:
        with make_client(timeout=20.0) as client:
            resp = client.get(url)
    except (httpx.HTTPError, OSError):
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        return job
    ctx: dict = {"status_code": resp.status_code}
    if resp.url:
        ctx["redirect_to"] = str(resp.url)
    if resp.status_code in (404, 410) or resp.status_code >= 500:
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        job._verify_ctx = ctx
        return job
    if resp.url and str(resp.url) != url:
        job.apply_url_direct = str(resp.url)
    job.employer_domain = _domain(job.apply_url_direct)
    if blocked_response(resp):
        ctx["blocked"] = True
        job._verify_ctx = ctx
        job.missing_fields.append("verified_reachable")
        job.confidence_score = min(job.confidence_score, SCORE_BLOCKED_CAP)
        return job
    snippet = resp_text(resp)[:8000].lower()
    marker = next((m for m in CLOSED_MARKERS if m in snippet), "")
    if marker:
        ctx["closed_marker"] = marker
        if "position has been filled" in marker:
            ctx["position_filled"] = True
        if any(m in snippet for m in ("captcha", "are you a robot", "verify you are human")):
            ctx["captcha"] = True
        job._verify_ctx = ctx
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        return job
    job._verify_ctx = ctx
    # Domain matches employer name -> boost confidence
    if job.employer_domain and job.company:
        hint = _company_domain_hint(job.company)
        if hint and hint in job.employer_domain:
            job.confidence_score = min(100, job.confidence_score + SCORE_DOMAIN_MATCH_BOOST)
        else:
            job.confidence_score = min(job.confidence_score, SCORE_DOMAIN_MATCH_CAP)
    return job


def _is_expired(valid_through: str) -> bool:
    if not valid_through or valid_through == MISSING:
        return False
    parsed = _parse_date(valid_through)
    if parsed is None:
        return False
    return parsed.timestamp() < time.time()


def _score_base(job: Job) -> int:
    """Confidence from algo.authenticity_features + existing weighting.

    Semantics identical to the original loop (6 fields x 8pts completeness,
    freshness, ATS-source bonus, expired validThrough penalty); only the source
    of the feature values moved into algo.py. Never called "probability".
    """
    feats = algo.authenticity_features(job)
    score = int(round(feats["completeness"] * SCORE_COMPLETENESS_WEIGHT))
    fr = job.freshness or freshness_label(job.date_posted)
    job.freshness = fr
    if fr == "fresh":
        score += SCORE_FRESH_BONUS
    elif fr == "recent":
        score += SCORE_RECENT_BONUS
    elif fr == "older":
        score += SCORE_OLDER_BONUS
    elif fr == "stale":
        score -= SCORE_STALE_PENALTY
    # Aggregator-only sources are slightly less trusted than employer ATS.
    # Derived from the single SOURCE_AUTHORITY map (evidence/source.py).
    if source_authority(job.source_name) >= SCORE_ATS_MIN_AUTHORITY:
        score += SCORE_ATS_BOOST
    # staleness by age even when date present: use valid_through if available
    if job.valid_through and _is_expired(job.valid_through):
        score -= SCORE_EXPIRED_PENALTY
    return max(0, min(SCORE_CAP, score))
