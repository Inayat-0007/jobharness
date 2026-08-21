from __future__ import annotations

import re

# Source-specific posting-ID extraction, then generic fallbacks.
# Order matters: source rules run first, generic rules last.


def extract_posting_id(job) -> str:
    """Extract an external posting ID from a Job.

    Rules: greenhouse job id, lever job id, remoteok numeric slug, adzuna id,
    LinkedIn numeric job id, naukri slug id, hirist job id, internshala
    detail id, wellfound/angel.co job id, indeed jk param, glassdoor jl
    param, google jobs jid/htidocid param, RSS numeric ids, then generic
    trailing-numeric fallback.
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
    elif sname == "naukri":
        m = re.search(r"/job-listings-[a-z0-9-]*?(\d{9,})", url) or re.search(
            r"/job/[a-z0-9-]*?(\d{9,})", url
        )
        if m:
            return m.group(1)
    elif sname == "hirist":
        m = re.search(r"/(?:job|j)/[a-z0-9-]*?(\d{8,})", url)
        if m:
            return m.group(1)
    elif sname == "internshala":
        m = re.search(r"/internship/detail/(?:[a-z0-9-]+-)?([a-z0-9]{16,})(?:/|$|\?)", url) or re.search(
            r"/internship/detail/[a-z0-9-]*?(\d{8,})", url
        )
        if m:
            return m.group(1)
    elif sname == "wellfound":
        m = re.search(r"/jobs?/(\d{6,})", url) or re.search(
            r"angel\.co/[^/]+/jobs/(\d{6,})", url
        )
        if m:
            return m.group(1)
    elif sname == "indeed":
        m = re.search(r"[?&]jk=([a-zA-Z0-9]{16,})", url)
        if m:
            return m.group(1)
    elif sname == "glassdoor":
        m = re.search(r"[?&]jl=(\d{9,})", url)
        if m:
            return m.group(1)
    elif sname == "google_jobs":
        m = re.search(r"[?&](?:jid|htidocid)=([a-zA-Z0-9_:-]+)", url) or re.search(
            r"/jobs/(\d{6,})", url
        )
        if m:
            return m.group(1)
    elif sname in ("remotive", "weworkremotely", "jobicy"):
        m = re.search(r"/remote-jobs/[a-z0-9/-]*?(\d{6,})", url) or re.search(
            r"/(?:jobs|job)/[a-z0-9/-]*?(\d{6,})", url
        )
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
