from __future__ import annotations

from .thresholds import (
    AUTO_ACCEPT,
    AUTO_ACCEPT_AUTHENTICITY,
    AUTO_ACCEPT_IDENTITY,
    AUTO_ACCEPT_MATCH,
    MEDIUM_AUTHENTICITY,
    MIN_UNCERTAIN_IDENTITY,
    REJECT,
    REVIEW,
    REVIEW_MATCH,
    STATE_CLOSED,
    STATE_EXCLUDED,
    STATE_INVALID_URL,
)

_HARD_REASONS = {
    STATE_CLOSED: "job closed",
    STATE_EXCLUDED: "hard exclusion",
    STATE_INVALID_URL: "invalid application URL",
}


def _identity_passes(identity_score: float) -> bool:
    """Identity criterion for AUTO_ACCEPT: very high similarity OR no
    candidates at all (genuinely-new job with no known duplicates)."""
    return identity_score >= AUTO_ACCEPT_IDENTITY or identity_score == 0.0


def decide(identity_score: float, authenticity_score: float, match_score: float, job_state: str) -> tuple[str, list[str]]:
    """(decision, reasons) from the three scores + job state.

    - CLOSED / hard exclusion / invalid URL -> REJECT
    - identity very high (or no candidates) AND authenticity high AND
      relevance high -> AUTO_ACCEPT
    - uncertain identity (MEDIUM fuzzy) OR medium authenticity OR medium
      relevance -> REVIEW
    - otherwise -> REJECT
    """
    if job_state in _HARD_REASONS:
        return REJECT, [_HARD_REASONS[job_state]]

    if (
        _identity_passes(identity_score)
        and authenticity_score >= AUTO_ACCEPT_AUTHENTICITY
        and match_score >= AUTO_ACCEPT_MATCH
    ):
        reasons = ["identity very high", "authenticity high", "relevance high"]
        if identity_score == 0.0:
            reasons[0] = "no known duplicates"
        return AUTO_ACCEPT, reasons

    reasons = []
    if REVIEW_MATCH <= match_score < AUTO_ACCEPT_MATCH:
        reasons.append("relevance medium")
    if MIN_UNCERTAIN_IDENTITY <= identity_score < AUTO_ACCEPT_IDENTITY:
        reasons.append("identity uncertain")
    if MEDIUM_AUTHENTICITY <= authenticity_score < AUTO_ACCEPT_AUTHENTICITY:
        reasons.append("authenticity medium")
    if reasons:
        return REVIEW, reasons
    return REJECT, ["below all thresholds"]
