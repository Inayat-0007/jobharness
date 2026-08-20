from __future__ import annotations

import hashlib
import math
import re
import time as _time
from urllib.parse import urlsplit

# Guarded optional accelerator: rapidfuzz is NOT a hard dependency. When absent
# (the common case) every algorithm below is pure Python and behavior-identical.
try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz  # type: ignore

    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

# Centralized thresholds. Never scatter these numbers in runner/verify/matcher.
TITLE_FLOOR = 0.75
HIGH_THRESHOLD = 0.88
REVIEW_THRESHOLD = 0.80

_COMPANY_SUFFIXES = (
    "inc",
    "llc",
    "ltd",
    "corp",
    "corporation",
    "co",
    "gmbh",
    "the",
    "technologies",
    "group",
    "solutions",
    "systems",
    "labs",
    "software",
    "digital",
)
_LEVEL_WORDS = ("senior", "junior", "mid", "lead", "principal", "staff", "sr", "jr", "i", "ii", "iii", "iv")
_REMOTE_WORDS = ("remote", "worldwide", "anywhere", "work from home", "wfh", "global")


def _norm_text(text) -> str:
    if not text:
        return ""
    t = str(text).strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", "", t)
    return t.strip()


normalize_text = _norm_text


def company_domain_hint(company) -> str:
    """Derive an expected employer domain token from the company name.
    Single implementation; verify.py and evidence builders delegate here."""
    if not company:
        return ""
    c = re.sub(r"[^a-z0-9]+", " ", str(company).lower()).strip()
    c = re.sub(r"\s+(inc|llc|ltd|corp|corporation|co|gmbh|the)$", "", c).strip()
    return c.replace(" ", "")


def jaro_winkler(a, b) -> float:
    """Jaro-Winkler similarity, pure-Python implementation.

    `match_distance = max(0, max(len1, len2) // 2 - 1)` protects short strings
    (e.g. 1-char and empty inputs never produce a negative window or crash).
    """
    a = str(a or "").lower()
    b = str(b or "").lower()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    len1, len2 = len(a), len(b)
    match_distance = max(0, max(len1, len2) // 2 - 1)
    matched_a = [False] * len1
    matched_b = [False] * len2
    m = 0
    for i, ca in enumerate(a):
        lo = max(0, i - match_distance)
        hi = min(i + match_distance + 1, len2)
        for j in range(lo, hi):
            if not matched_b[j] and ca == b[j]:
                matched_a[i] = True
                matched_b[j] = True
                m += 1
                break
    if m == 0:
        return 0.0
    t = 0
    k = 0
    for i in range(len1):
        if not matched_a[i]:
            continue
        while not matched_b[k]:
            k += 1
        if a[i] != b[k]:
            t += 1
        k += 1
    t //= 2
    jaro = (m / len1 + m / len2 + (m - t) / m) / 3.0
    prefix = 0
    for i in range(min(4, len1, len2)):
        if a[i] == b[i]:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1.0 - jaro)


def token_shingles(text, n: int = 3) -> set:
    """Exact token-level shingles (not MinHash)."""
    tokens = _norm_text(text).split()
    if not tokens:
        return set()
    if len(tokens) < n:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(s1, s2) -> float:
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    inter = len(s1 & s2)
    union = len(s1 | s2)
    return inter / union if union else 0.0


def description_similarity(desc1, desc2) -> float:
    # Missing descriptions are neutral (0.5), never evidence of identity or
    # difference. One-sided presence is also inconclusive (0.5) — stored rows
    # from pre-v3 migrations may lack the column.
    if not desc1 or not desc2:
        return 0.5
    return jaccard(token_shingles(desc1), token_shingles(desc2))


def normalize_company(name) -> str:
    """Single implementation of company-name normalization (suffix stripping,
    punctuation removal). `identity/company.py` delegates here."""
    if not name:
        return ""
    c = str(name).strip().lower()
    c = re.sub(r"[^a-z0-9 ]+", " ", c)
    c = re.sub(r"\s+", " ", c).strip()
    words = c.split()
    while words and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def _norm_domain(domain) -> str:
    if not domain:
        return ""
    d = str(domain).strip().lower().rstrip("/")
    if d.startswith("www."):
        d = d[4:]
    d = d.split("@")[-1]
    if "://" in d:
        d = urlsplit(d).netloc or d
    return d


def _domain_from_url(url) -> str:
    if not url:
        return ""
    try:
        net = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    net = net.split("@")[-1]
    if net.startswith("www."):
        net = net[4:]
    return net


def company_similarity(name1, name2, domain1="", domain2="", url1="", url2="") -> float:
    """C = 0.45*C_name + 0.35*C_domain + 0.20*C_url with a safety rule table:

    - high name sim + matching domain -> strong (min 0.95)
    - high name sim + conflicting domain -> review (max 0.55)
    - high name sim + unknown domain -> uncertain (no adjustment)
    A single differing char (Levenshtein 1) never decides identity on its own:
    it only moves C_name, and the domain/url terms stay independent.
    """
    n1 = normalize_company(name1)
    n2 = normalize_company(name2)
    if n1 and n2:
        c_name = jaro_winkler(n1, n2)
    else:
        c_name = 1.0 if (not n1 and not n2) else 0.5

    d1 = _norm_domain(domain1) or _norm_domain(_domain_from_url(url1))
    d2 = _norm_domain(domain2) or _norm_domain(_domain_from_url(url2))
    if d1 and d2:
        c_domain = 1.0 if d1 == d2 else 0.0
    else:
        c_domain = 0.5

    u1 = _norm_domain(_domain_from_url(url1))
    u2 = _norm_domain(_domain_from_url(url2))
    if u1 and u2:
        c_url = 1.0 if u1 == u2 else 0.0
    else:
        c_url = 0.5

    c = 0.45 * c_name + 0.35 * c_domain + 0.20 * c_url
    if n1 and n2 and c_name >= 0.90:
        if d1 and d2:
            if d1 == d2:
                c = max(c, 0.95)
            else:
                c = min(c, 0.55)
    return round(c, 4)


def company_identity_pass(name1, name2, domain1="", domain2="", url1="", url2="") -> bool:
    """Company identity gate for auto-merge: no strong contradiction and no
    evidence the companies differ."""
    return company_similarity(name1, name2, domain1, domain2, url1, url2) >= 0.60


def location_similarity(loc1, loc2) -> float:
    if not loc1 and not loc2:
        return 1.0
    if not loc1 or not loc2:
        return 0.5
    if str(loc1).strip().lower() == str(loc2).strip().lower():
        return 1.0
    t1 = _loc_tokens(loc1)
    t2 = _loc_tokens(loc2)
    return jaccard(set(t1), set(t2))


def _loc_tokens(loc) -> list[str]:
    if not loc:
        return []
    t = str(loc).strip().lower()
    for w in _REMOTE_WORDS:
        t = re.sub(r"\b" + re.escape(w) + r"\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return [tok for tok in t.split() if tok]


def location_bucket(loc) -> str:
    """'remote' / city / region / country tokens. Single implementation used by
    blocking key 2; `identity/location.py` delegates here."""
    if not loc:
        return ""
    tokens = _loc_tokens(loc)
    if tokens:
        return " ".join(tokens)
    return "remote" if any(w in str(loc).lower() for w in _REMOTE_WORDS) else ""


def title_stem(title) -> str:
    """First 2 normalized title tokens, seniority/level words removed."""
    if not title:
        return ""
    tokens = _norm_text(title).split()
    tokens = [t for t in tokens if t not in _LEVEL_WORDS]
    return " ".join(tokens[:2])


def blocking_keys(job) -> list[str]:
    """Five blocking keys; empty components are omitted:
    1. normalized_company + title_stem
    2. normalized_company + location_bucket
    3. company_domain + title_stem
    4. external_posting_id
    5. canonical_apply_domain + title_stem
    """
    keys: list[str] = []
    company = normalize_company(getattr(job, "company", ""))
    stem = title_stem(getattr(job, "title", ""))
    bucket = location_bucket(getattr(job, "location", ""))
    domain = _norm_domain(
        getattr(job, "employer_domain", "") or _domain_from_url(getattr(job, "apply_url_direct", ""))
    )
    posting_id = str(getattr(job, "posting_id", "") or "").strip()
    if company and stem:
        keys.append(f"{company}|{stem}")
    if company and bucket:
        keys.append(f"{company}|{bucket}")
    if domain and stem:
        keys.append(f"{domain}|{stem}")
    if posting_id:
        keys.append(posting_id)
    if domain and stem:
        keys.append(f"apply:{domain}|{stem}")
    return keys


def composite_similarity(
    title1,
    company1,
    location1,
    desc1,
    title2,
    company2,
    location2,
    desc2,
    domain1="",
    domain2="",
    url1="",
    url2="",
) -> tuple[str, float]:
    """S = 0.35*S_title + 0.25*S_company + 0.15*S_location + 0.25*S_desc.

    Verdicts:
    - "none" if S_title < TITLE_FLOOR (hard gate)
    - "auto_merge" if S >= HIGH_THRESHOLD AND company identity pass AND no
      hard contradiction
    - "review" if S >= REVIEW_THRESHOLD
    - else "none"
    """
    s_title = jaro_winkler(title1, title2)
    s_company = company_similarity(company1, company2, domain1, domain2, url1, url2)
    s_location = location_similarity(location1, location2)
    s_desc = description_similarity(desc1, desc2)
    s = 0.35 * s_title + 0.25 * s_company + 0.15 * s_location + 0.25 * s_desc
    if s_title < TITLE_FLOOR:
        return "none", round(s, 4)
    contradiction = company_contradiction(company1, company2, domain1, domain2, url1, url2)
    if (
        s >= HIGH_THRESHOLD
        and company_identity_pass(company1, company2, domain1, domain2, url1, url2)
        and not contradiction
    ):
        return "auto_merge", round(s, 4)
    if s >= REVIEW_THRESHOLD:
        return "review", round(s, 4)
    return "none", round(s, 4)


def company_contradiction(name1, name2, domain1="", domain2="", url1="", url2="") -> bool:
    """Hard contradiction: both domains known and they differ while both
    company names are known. Blocks auto-merge regardless of S."""
    d1 = _norm_domain(domain1) or _norm_domain(_domain_from_url(url1))
    d2 = _norm_domain(domain2) or _norm_domain(_domain_from_url(url2))
    n1 = normalize_company(name1)
    n2 = normalize_company(name2)
    if not d1 or not d2:
        return False
    if d1 == d2:
        return False
    if not n1 or not n2:
        return False
    return jaro_winkler(n1, n2) >= 0.60


def description_fingerprint(desc) -> str:
    """sha1 of sorted token shingles (exact, not MinHash)."""
    shingles = token_shingles(desc)
    if not shingles:
        return ""
    raw = "|".join(sorted(shingles))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def bm25_idf(term, df: int, n_docs: int) -> float:
    """Standard BM25 idf with smoothing."""
    return math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


def bm25_score(
    query_terms,
    doc_terms,
    k1: float = 1.5,
    b: float = 0.75,
    avgdl: float | None = None,
    idf_map: dict | None = None,
) -> float:
    """BM25 relevance of a document for a query. Pure Python.

    - `doc_terms`: list[str] of the document's terms (duplicates allowed).
    - `avgdl`: average document length; defaults to this document's length.
    - `idf_map`: optional {term: idf}; when None, every query term is treated
      as equally rare (idf folded to 1.0) so the score is TF-weighted.
    """
    if not query_terms or not doc_terms:
        return 0.0
    doc_len = len(doc_terms)
    avdl = avgdl if avgdl is not None else float(doc_len)
    from collections import Counter

    freqs = Counter(doc_terms)
    score = 0.0
    for qt in query_terms:
        f = freqs.get(qt, 0)
        if f == 0:
            continue
        idf = (idf_map or {}).get(qt, 1.0)
        denom = f + k1 * (1.0 - b + b * doc_len / avdl) if avdl else f
        score += idf * (f * (k1 + 1.0)) / denom
    return round(score, 6)


def authenticity_features(job) -> dict[str, float]:
    """Raw feature vector for authenticity (never called "probability").
    Consumed by verify (Phase 1) and logistic regression (Phase 4)."""
    from .models import CLOSED, MISSING

    company = getattr(job, "company", "") or ""
    hint = company_domain_hint(company)
    domain = getattr(job, "employer_domain", "") or ""
    domain_match = 1.0 if (hint and hint in domain.lower()) else 0.0

    freshness = getattr(job, "freshness", "") or ""
    fresh_score = {"fresh": 1.0, "recent": 0.7, "older": 0.4, "stale": 0.1}.get(freshness, 0.0)

    required = ("title", "company", "apply_url_direct", "date_posted", "location", "experience_needed")
    present = sum(1 for f in required if (getattr(job, f, "") or "") not in ("", MISSING))
    completeness = present / len(required)

    valid_through = getattr(job, "valid_through", "") or ""
    vt_valid = 0.0
    if valid_through and valid_through != MISSING:
        try:
            from .models import _parse_date
            parsed = _parse_date(valid_through)
            if parsed is not None and parsed.timestamp() > _time.time():
                vt_valid = 1.0
        except Exception:
            vt_valid = 0.0

    return {
        "source_authority": float(getattr(job, "source_authority", 0) or 0),
        "domain_match": domain_match,
        "posting_id": 1.0 if (getattr(job, "posting_id", "") or "") else 0.0,
        "http_status": 0.0 if getattr(job, "authentic_status", "") == CLOSED else 1.0,
        "validThrough": vt_valid,
        "freshness": fresh_score,
        "completeness": completeness,
        "cross_source": 1.0 if len(getattr(job, "seen_sources", []) or []) > 1 else 0.0,
        "closed_markers": 1.0 if getattr(job, "authentic_status", "") == CLOSED else 0.0,
    }
