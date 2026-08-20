from __future__ import annotations

from ..algo import company_domain_hint
from ..models import CLOSED, MISSING


def _verify_ctx_ok(ctx, key, default=False) -> bool:
    return bool(ctx and ctx.get(key, default))


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


def negative_signals(job, verify_result=None) -> list[str]:
    """Negative authenticity signals (proposal §17). Same verify_result shape
    as positive_signals."""
    sig: list[str] = []
    status_code = (verify_result or {}).get("status_code")
    ctx = verify_result or {}

    if status_code in (404, 410):
        sig.append("http_gone")

    vt = getattr(job, "valid_through", "") or ""
    if vt and vt != MISSING:
        from ..models import _parse_date
        import time as _time

        parsed = _parse_date(vt)
        if parsed is not None and parsed.timestamp() < _time.time():
            sig.append("expired_valid_through")

    if getattr(job, "authentic_status", "") == CLOSED and "http_gone" not in sig:
        sig.append("closed_state")

    if _verify_ctx_ok(job, "position_filled") or (
        ctx.get("closed_marker") and "position has been filled" in str(ctx.get("closed_marker")).lower()
    ):
        sig.append("position_filled")

    if _verify_ctx_ok(job, "generic_careers_redirect") or ctx.get("redirect_to") and "careers" in str(ctx.get("redirect_to")).lower():
        sig.append("generic_careers_redirect")

    domain = getattr(job, "employer_domain", "") or ""
    hint = company_domain_hint(getattr(job, "company", "") or "")
    if hint and domain and hint not in domain.lower():
        sig.append("employer_domain_mismatch")

    if not getattr(job, "apply_url_direct", "") or getattr(job, "apply_url_direct", "") == MISSING:
        sig.append("broken_application")

    if _verify_ctx_ok(job, "captcha") or ctx.get("blocked"):
        sig.append("captcha_required" if ctx.get("captcha") else "blocked_response")

    return sig
