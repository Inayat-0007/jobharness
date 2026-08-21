from __future__ import annotations

POSITIVE_REASONS = {
    "official_ats_source": "official ATS/API source",
    "official_domain": "apply URL on employer domain",
    "valid_posting_id": "external posting ID present",
    "active_application": "application is active",
    "current_posting": "recently posted",
    "structured_job_posting": "structured job posting data",
    "cross_source_agreement": "seen on multiple sources",
}

NEGATIVE_REASONS = {
    "http_gone": "apply URL returns 404/410",
    "expired_valid_through": "posting expired (validThrough in the past)",
    "closed_state": "job marked closed",
    "position_filled": "position has been filled",
    "generic_careers_redirect": "redirected to a generic careers page",
    "employer_domain_mismatch": "apply URL domain does not match employer",
    "broken_application": "no usable application URL",
    "captcha_required": "application blocked by captcha",
    "blocked_response": "application blocked (403/anti-bot)",
    "verification_unreachable": "verification failed (posting unreachable)",
    "affiliate_domain": "application goes through an affiliate domain",
}


def reason_text(signal: str) -> str:
    return POSITIVE_REASONS.get(signal) or NEGATIVE_REASONS.get(signal) or signal.replace("_", " ")


def compose_reasons(positive: list[str], negative: list[str]) -> list[str]:
    """Human-readable reasons, positives first."""
    out = [reason_text(s) for s in positive]
    out += [f"negative: {reason_text(s)}" for s in negative]
    return out
