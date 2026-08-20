from __future__ import annotations

import datetime as dt
import re
import time
from urllib.parse import urlparse

import httpx

from . import algo
from .models import Job, CLOSED, MISSING, VALID_AUTHENTIC, _parse_date, freshness_label
from .fetcher import make_client, blocked_response
from .urlutil import apply_url_domain as _domain
from .scoring.authenticity import authenticity_score as _authenticity_score
from .scoring.thresholds import REJECT as _REJECT_DECISION

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

STALE_DAYS = 45
BLOCKED_RETRY_MS = 0


def verify(job: Job, check_reachable: bool = True) -> Job:
    """Resolve apply_url, follow redirects, confirm not CLOSED, score confidence.

    Sets job.authentic_status = CLOSED (and decision = REJECT) if unreachable
    or a closed marker found. Computes job.confidence_score (0-100), sets
    employer_domain, and validates the apply URL host against the company name.
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
        job.confidence_score = min(job.confidence_score, 40)
        return job
    snippet = (resp.text or "")[:8000].lower()
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
            job.confidence_score = min(100, job.confidence_score + 25)
        else:
            job.confidence_score = min(job.confidence_score, 55)
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
    score = int(round(feats["completeness"] * 48))
    fr = job.freshness or freshness_label(job.date_posted)
    job.freshness = fr
    if fr == "fresh":
        score += 24
    elif fr == "recent":
        score += 16
    elif fr == "older":
        score += 4
    elif fr == "stale":
        score -= 10
    # Aggregator-only sources are slightly less trusted than employer ATS.
    if job.source_name in ("greenhouse", "lever", "career_page_generic", "usajobs"):
        score += 10
    # staleness by age even when date present: use valid_through if available
    if job.valid_through and _is_expired(job.valid_through):
        score -= 20
    return max(0, min(80, score))
