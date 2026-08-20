from __future__ import annotations

import httpx

from .models import Job, CLOSED, MISSING
from .fetcher import make_client, blocked_response


CLOSED_MARKERS = (
    "no longer accepting",
    "this position has been closed",
    "job has expired",
    "requisition has been closed",
    "this job posting is no longer active",
    "page not found",
    "404",
    "not found",
    "this requisition",
    "no longer open",
)


def verify(job: Job, check_reachable: bool = True) -> Job:
    """Resolve apply_url, follow redirects, confirm posting isn't CLOSED.

    Sets job.authentic_status = CLOSED if unreachable or a closed marker is found.
    """
    url = job.apply_url_direct
    if not url or url == MISSING:
        job.authentic_status = CLOSED
        return job
    if not check_reachable:
        return job
    try:
        with make_client(timeout=20.0) as client:
            resp = client.get(url)
    except (httpx.HTTPError, OSError):
        job.authentic_status = CLOSED
        return job
    if resp.status_code in (404, 410) or resp.status_code >= 500:
        job.authentic_status = CLOSED
        return job
    if blocked_response(resp):
        # Can't confirm reliably; leave as authentic but flag missing verification.
        job.missing_fields.append("verified_reachable")
        return job
    snippet = (resp.text or "")[:4000].lower()
    if any(m in snippet for m in CLOSED_MARKERS):
        job.authentic_status = CLOSED
        # If redirects landed on an employer domain, capture final url.
    if resp.url and str(resp.url) != url:
        job.apply_url_direct = str(resp.url)
    return job
