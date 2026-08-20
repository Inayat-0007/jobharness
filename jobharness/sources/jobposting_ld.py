from __future__ import annotations

import json
from typing import Iterable

from ..models import RawJob


def _get(obj, *path):
    cur = obj
    for k in path:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


def _as_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return _as_str(v[0]) if v else ""
    if isinstance(v, dict):
        for key in ("name", "@value", "value"):
            if v.get(key) is not None:
                return str(v[key])
        return ""
    return str(v)


def extract_jobpostings_from_html(html: str, source_name: str, seed_url: str, company_fallback: str = "") -> list[RawJob]:
    """Parse all schema.org/JobPosting JSON-LD blocks from rendered HTML.

    Fields come strictly from the JSON-LD. Missing fields stay ""/MISSING,
    never invented. Returns RawJobs with apply_url=url, posted_date=datePosted.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "lxml")
    out: list[RawJob] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string
        if not raw:
            continue
        try:
            blob = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = blob if isinstance(blob, list) else [blob]
        # Some sites nest an @graph of JobPostings
        for entry in candidates:
            typ = entry.get("@type") if isinstance(entry, dict) else None
            nested = _graph_jobpostings(entry)
            if nested:
                for bp in nested:
                    out.append(_from_ld(bp, source_name, seed_url, company_fallback))
            elif typ in ("JobPosting", ["JobPosting"]) or (
                isinstance(typ, list) and "JobPosting" in typ
            ):
                out.append(_from_ld(entry, source_name, seed_url, company_fallback))
    return out


def extract_jobpostings_from_blob(blob: dict | list, source_name: str, seed_url: str, company_fallback: str = "") -> list[RawJob]:
    """Parse JobPosting objects already decoded from JSON (e.g. an API blob)."""
    out: list[RawJob] = []
    entries = blob if isinstance(blob, list) else [blob]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        nested = _graph_jobpostings(entry)
        if nested:
            for bp in nested:
                out.append(_from_ld(bp, source_name, seed_url, company_fallback))
        elif _is_jobposting(entry):
            out.append(_from_ld(entry, source_name, seed_url, company_fallback))
    return out


def _is_jobposting(entry: dict) -> bool:
    typ = entry.get("@type")
    if typ == "JobPosting":
        return True
    if isinstance(typ, list) and "JobPosting" in typ:
        return True
    return False


def _graph_jobpostings(entry: dict) -> Iterable[dict]:
    g = entry.get("@graph") if isinstance(entry, dict) else None
    if isinstance(g, list):
        return [x for x in g if isinstance(x, dict) and _is_jobposting(x)]
    return []


def _from_ld(ld: dict, source_name: str, seed_url: str, company_fallback: str) -> RawJob:
    org = ld.get("hiringOrganization") or {}
    company = _as_str(org.get("name") if isinstance(org, dict) else org) or company_fallback
    loc = ld.get("jobLocation") or ld.get("applicantLocationRequirements") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    loc_str = ""
    if isinstance(loc, dict):
        addr = loc.get("address", {})
        if isinstance(addr, list):
            addr = addr[0] if addr else {}
        if isinstance(addr, dict):
            loc_str = ", ".join(
                str(v) for v in (addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")) if v
            ).strip(", ")
        elif addr:
            loc_str = str(addr)
    elif loc:
        loc_str = str(loc)
    remote = bool(ld.get("jobLocationType")) and "remote" in str(ld.get("jobLocationType", "")).lower()
    employment = _as_str(ld.get("employmentType"))
    salary = ld.get("baseSalary") or {}
    salary_str = ""
    if isinstance(salary, dict):
        cur = _as_str(salary.get("currency"))
        value = salary.get("value") or salary.get("baseSalary") or {}
        if isinstance(value, dict):
            mn = value.get("minValue")
            mx = value.get("maxValue")
            if mn is not None or mx is not None:
                lo = _as_str(mn) if mn is not None else ""
                hi = _as_str(mx) if mx is not None else ""
                range_part = f"{lo}-{hi}" if lo and hi else (lo or hi)
                salary_str = f"{range_part} {cur}".strip()
            elif value.get("value") is not None:
                salary_str = f"{_as_str(value.get('value'))} {cur}".strip()
            elif isinstance(value.get("value"), list) and value["value"]:
                salary_str = f"{_as_str(value['value'][0])} {cur}".strip()
        elif isinstance(value, list) and value:
            salary_str = f"{_as_str(value[0])} {cur}".strip()
    return RawJob(
        source_name=source_name,
        source_url=ld.get("url", seed_url) or seed_url,
        title=_as_str(ld.get("title")),
        company=company,
        location=loc_str,
        description=_as_str(ld.get("description")),
        posted_date=_as_str(ld.get("datePosted")),
        apply_url=_as_str(ld.get("url")) or seed_url,
        extra={
            "valid_through": _as_str(ld.get("validThrough")),
            "employment_type": employment,
            "salary": salary_str,
            "remote": remote,
            "qualifications": _as_str(ld.get("qualifications")),
            "hiring_org_sameas": _as_str(org.get("sameAs")) if isinstance(org, dict) else "",
        },
    )
