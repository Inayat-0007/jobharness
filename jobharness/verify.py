from __future__ import annotations

import time

import httpx

from . import algo, verify_cache
from .evidence.source import source_authority
from .fetcher import blocked_response, get_shared_client
from .models import CLOSED, MISSING, Job, _parse_date, freshness_label
from .scoring.authenticity import authenticity_score as _authenticity_score
from .scoring.thresholds import (
    REJECT as _REJECT_DECISION,
)
from .scoring.thresholds import (
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
from .urlutil import apply_url_domain as _domain

_company_domain_hint = algo.company_domain_hint

# Status for jobs whose posting could not be confirmed reachable because of
# transient failures (network errors, 408/429/5xx). Unlike CLOSED this is not
# a hard exclusion: the runner only special-cases "CLOSED".
DEGRADED = "DEGRADED"

# Retry policy: up to 2 retries with exponential backoff (0.5s, then 2s).
_RETRY_DELAYS = (0.5, 2.0)
_MAX_RETRIES = len(_RETRY_DELAYS)
_VERIFY_TIMEOUT = 20.0
_SNIPPET_CHARS = 8000
_STREAM_CHUNK = 8192
_DEGRADED_PENALTY = 15
_UNREACHABLE_SIGNAL = "verification_unreachable"

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


def _transient_status(code: int) -> bool:
    # LinkedIn 999 rate limit
    return code in (408, 429) or code == 999 or 500 <= code < 600


def _degraded_failure_class(status_code: int) -> str:
    """Classify a DEGRADED job's failure for the Telegram warning text:
    429/999 are rate limits; 408/5xx are server-side errors; anything else
    (network exceptions) is a network error."""
    if status_code in (429, 999):
        return "rate_limited"
    return "server_error"


class _SnippetResponse(httpx.Response):
    """Stand-in for fetcher.blocked_response after the stream body is consumed."""

    def __init__(self, status_code: int, snippet: str):
        super().__init__(status_code=status_code, content=snippet.encode("utf-8"))


def _fetch_snippet(client: httpx.Client, url: str, timeout: float = _VERIFY_TIMEOUT) -> tuple[httpx.Response, str]:
    """GET a URL, streaming only the first ~8k chars of the body.

    Statuses whose bodies are never inspected (404/410, 408/429/5xx) return
    immediately without downloading the body.  The stream is always closed
    before returning.
    """
    with client.stream("GET", url, timeout=timeout) as resp:
        if resp.status_code in (404, 410) or _transient_status(resp.status_code):
            return resp, ""
        buf = b""
        for chunk in resp.iter_bytes(_STREAM_CHUNK):
            buf += chunk
            if len(buf) >= 2 * _SNIPPET_CHARS:
                break
    return resp, buf.decode("utf-8", errors="replace")[:_SNIPPET_CHARS]


def _mark_degraded(job: Job, ctx: dict) -> Job:
    """Mark a job DEGRADED after transient retries are exhausted; ctx carries
    status/retries/failure_class used by the notification layer.

    Never CLOSED: the job may still be live; we just could not confirm it.
    """
    job.authentic_status = DEGRADED
    job.confidence_score = max(0, job.confidence_score - _DEGRADED_PENALTY)
    job._verify_ctx = ctx
    for signals in (job.negative_evidence, job.reason):
        if _UNREACHABLE_SIGNAL not in signals:
            signals.append(_UNREACHABLE_SIGNAL)
    return job


def verify(job: Job, check_reachable: bool = True) -> Job:
    """Resolve apply_url, follow redirects, confirm not CLOSED, score confidence.

    Sets job.authentic_status = CLOSED (and decision = REJECT) for hard
    failures (404/410, closed markers). Transient failures (network errors,
    408/429/5xx) are retried twice with exponential backoff; if they persist
    the job is marked DEGRADED with a "verification_unreachable" negative
    signal, a small confidence penalty, and a failure class recorded for
    accurate card messaging (not CLOSED). Computes
    job.confidence_score (0-100), sets employer_domain, and scores the apply
    URL host against the company name.
    """
    job.confidence_score = _score_base(job)
    job.authenticity_score = float(_authenticity_score(job))
    url = job.apply_url_direct
    if not url or url == MISSING:
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        return job
    if _is_expired(job.valid_through):
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        return job
    if not check_reachable:
        return job

    # Cache: a definitive outcome from a recent run lets us skip the network
    # fetch entirely. This is what stops the LinkedIn 429 storm on repeat runs
    # (the same apply URLs were re-requested every run). Transient/DEGRADED
    # results are never cached, so a flaky URL is retried next run.
    cached = verify_cache.lookup(url)
    if cached is not None:
        cache_ctx: dict[str, int | str] = {"status_code": cached["status_code"] or 0}
        if cached.get("redirect_to"):
            cache_ctx["redirect_to"] = cached["redirect_to"]
        if cached["status"] == "closed":
            job.authentic_status = CLOSED
            job.decision = _REJECT_DECISION
            job._verify_ctx = cache_ctx
            return job
        # Cached 'ok': treat as reachable. Apply the domain-match scoring so
        # confidence stays consistent with a live fetch (the score base is
        # already computed above).
        job.employer_domain = _domain(url)
        job._verify_ctx = cache_ctx
        if job.employer_domain and job.company:
            hint = _company_domain_hint(job.company)
            if hint and hint in job.employer_domain:
                job.confidence_score = min(100, job.confidence_score + SCORE_DOMAIN_MATCH_BOOST)
            else:
                job.confidence_score = min(job.confidence_score, SCORE_DOMAIN_MATCH_CAP)
        return job

    client = get_shared_client()
    resp: httpx.Response | None = None
    snippet = ""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp, snippet = _fetch_snippet(client, url)
        except (TimeoutError, httpx.HTTPError, OSError) as exc:
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAYS[attempt])
                continue
            return _mark_degraded(
                job, {"retries": attempt, "error": str(exc), "failure_class": "network_error"}
            )
        if _transient_status(resp.status_code):
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAYS[attempt])
                continue
            ctx: dict[str, int | str] = {
                "status_code": resp.status_code,
                "retries": attempt,
                "failure_class": _degraded_failure_class(resp.status_code),
            }
            if resp.url:
                ctx["redirect_to"] = str(resp.url)
            return _mark_degraded(job, ctx)
        break
    assert resp is not None
    ctx = {"status_code": resp.status_code}
    if resp.url:
        ctx["redirect_to"] = str(resp.url)
    if resp.status_code in (404, 410):
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        job._verify_ctx = ctx
        verify_cache.record(url, "closed", resp.status_code, str(ctx.get("redirect_to") or ""))
        return job
    if resp.url and str(resp.url) != url:
        job.apply_url_direct = str(resp.url)
    job.employer_domain = _domain(job.apply_url_direct)
    if blocked_response(_SnippetResponse(resp.status_code, snippet)):
        ctx["blocked"] = True
        job._verify_ctx = ctx
        job.missing_fields.append("verified_reachable")
        job.confidence_score = min(job.confidence_score, SCORE_BLOCKED_CAP)
        return job
    low = snippet.lower()
    marker = next((m for m in CLOSED_MARKERS if m in low), "")
    if marker:
        ctx["closed_marker"] = marker
        if "position has been filled" in marker:
            ctx["position_filled"] = True
        if any(m in low for m in ("captcha", "are you a robot", "verify you are human")):
            ctx["captcha"] = True
        job._verify_ctx = ctx
        job.authentic_status = CLOSED
        job.decision = _REJECT_DECISION
        verify_cache.record(url, "closed", resp.status_code, str(ctx.get("redirect_to") or ""))
        return job
    job._verify_ctx = ctx
    if job.employer_domain and job.company:
        hint = _company_domain_hint(job.company)
        if hint and hint in job.employer_domain:
            job.confidence_score = min(100, job.confidence_score + SCORE_DOMAIN_MATCH_BOOST)
        else:
            job.confidence_score = min(job.confidence_score, SCORE_DOMAIN_MATCH_CAP)
    verify_cache.record(url, "ok", resp.status_code, str(ctx.get("redirect_to") or ""))
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
    if source_authority(job.source_name) >= SCORE_ATS_MIN_AUTHORITY:
        score += SCORE_ATS_BOOST
    if job.valid_through and _is_expired(job.valid_through):
        score -= SCORE_EXPIRED_PENALTY
    return max(0, min(SCORE_CAP, score))
