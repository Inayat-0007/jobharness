from __future__ import annotations

import re

# Source-specific posting-ID extraction, then generic fallbacks.
# Order matters: source rules run first, generic rules last.


def extract_posting_id(job) -> str:
    """Extract an external posting ID from a Job.

    Rules: greenhouse job id, lever job id, remoteok numeric slug, adzuna id,
    LinkedIn numeric job id, generic trailing-numeric fallback.
    """
    url = getattr(job, "apply_url_direct", "") or getattr(job, "source_url", "") or ""
    sname = str(getattr(job, "source_name", "") or "").lower()

    if sname == "greenhouse":
        m = re.search(r"/jobs/(\d{5,})", url)
        if m:
            return m.group(1)
    elif sname == "lever":
        m = re.search(r"lever\.co/(?:[\w-]+/)?([a-z0-9-]{8,})(?:/|$|\?)", url)
        if m:
            return m.group(1)
    elif sname == "remoteok":
        m = re.search(r"/(\d{4,})[a-z0-9-]*", url)
        if m:
            return m.group(1)
    elif sname == "adzuna":
        m = re.search(r"/ad/(\d{4,})", url)
        if m:
            return m.group(1)
    elif sname == "linkedin":
        m = re.search(r"/jobs/view/(\d{7,})", url)
        if m:
            return m.group(1)

    # Generic explicit identifiers (JSON-LD @id / adapter extras).
    for key in ("posting_id", "identifier", "job_id"):
        v = getattr(job, key, "") or ""
        if v:
            return str(v)

    # Generic fallback: long trailing numeric id (USAJobs ControlNumber-style).
    m = re.search(r"/(\d{8,})(?:/|\?|$)", url)
    if m:
        return m.group(1)
    return ""
