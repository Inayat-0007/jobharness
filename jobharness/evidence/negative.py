from __future__ import annotations

import time as _time

from ..algo import company_domain_hint
from ..models import CLOSED, MISSING, _parse_date


def negative_signals(job, verify_result=None) -> list[str]:
    """Negative authenticity signals (proposal §17). verify_result is an
    optional dict from verify() with keys: status_code, blocked, closed_marker,
    redirect_to, captcha, position_filled. Feature-derived fallbacks apply
    when it is absent."""
    sig: list[str] = []
    ctx = verify_result or {}
    status_code = ctx.get("status_code")

    if status_code in (404, 410):
        sig.append("http_gone")

    vt = getattr(job, "valid_through", "") or ""
    if vt and vt != MISSING:
        parsed = _parse_date(vt)
        if parsed is not None and parsed.timestamp() < _time.time():
            sig.append("expired_valid_through")

    if getattr(job, "authentic_status", "") == CLOSED and "http_gone" not in sig:
        sig.append("closed_state")

    marker = str(ctx.get("closed_marker") or "").lower()
    if ctx.get("position_filled") or "position has been filled" in marker:
        sig.append("position_filled")

    if ctx.get("generic_careers_redirect") or (
        ctx.get("redirect_to") and "careers" in str(ctx.get("redirect_to")).lower()
    ):
        sig.append("generic_careers_redirect")

    domain = getattr(job, "employer_domain", "") or ""
    hint = company_domain_hint(getattr(job, "company", "") or "")
    if hint and domain and hint not in domain.lower():
        sig.append("employer_domain_mismatch")

    if not getattr(job, "apply_url_direct", "") or getattr(job, "apply_url_direct", "") == MISSING:
        sig.append("broken_application")

    if ctx.get("captcha"):
        sig.append("captcha_required")
    elif ctx.get("blocked"):
        sig.append("blocked_response")

    return sig
