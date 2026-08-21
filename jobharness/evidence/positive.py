from __future__ import annotations

from ..algo import company_domain_hint
from ..models import CLOSED


def positive_signals(job, verify_result=None) -> list[str]:
    """Positive authenticity signals (proposal §17). verify_result is an
    optional dict from verify() with keys: status_code, blocked, closed_marker,
    redirect_to. Feature-derived fallbacks apply when it is absent."""
    sig: list[str] = []

    authority = getattr(job, "source_authority", 0) or 0
    if authority >= 4:
        sig.append("official_ats_source")

    domain = getattr(job, "employer_domain", "") or ""
    hint = company_domain_hint(getattr(job, "company", "") or "")
    if hint and hint in (domain or "").lower():
        sig.append("official_domain")

    if getattr(job, "posting_id", ""):
        sig.append("valid_posting_id")

    status_code = (verify_result or {}).get("status_code")
    if getattr(job, "authentic_status", "") != CLOSED and status_code not in (404, 410):
        sig.append("active_application")

    if getattr(job, "freshness", "") in ("fresh", "recent"):
        sig.append("current_posting")

    if str(getattr(job, "source_name", "") or "").lower() == "google_jobs":
        sig.append("structured_job_posting")

    if len(getattr(job, "seen_sources", []) or []) > 1:
        sig.append("cross_source_agreement")

    return sig
