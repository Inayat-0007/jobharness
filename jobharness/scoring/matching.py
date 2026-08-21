from __future__ import annotations

from .. import algo

# Skill synonym map: canonical term per normalized input form. Terms are
# normalized (lowercase, punctuation stripped, c++/c# special-cased) before
# lookup, so keys are already in normalized form.
SKILL_SYNONYMS = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "ts": "typescript",
    "node": "nodejs",
    "reactjs": "react",
    "k8s": "kubernetes",
    "gcp": "google cloud",
    "amazon web services": "aws",
}


def skill_normalize(term) -> str:
    t = str(term or "").strip().lower()
    t = t.replace("c++", "cpp").replace("c#", "csharp")
    t = algo.normalize_text(t)
    return SKILL_SYNONYMS.get(t, t)


# Saturation caps for coverage normalization (calibration fix, 2026-08).
# The raw query term/keyword counts grow with the profile size (e.g. 33 roles
# + 47 keywords = 74 unique query tokens), so dividing the BM25 sum or the
# matched-keyword count by the FULL profile size made strong scores
# unreachable: a perfect title match scored ~0.06-0.15 and no job ever passed
# AUTO_ACCEPT_MATCH (observed max match_score 0.230 over 183+ matched jobs).
# Instead we treat a job matching ~8 distinct query tokens (or ~8 profile
# keywords) as a saturated match and cap the denominator there.
BM25_SATURATION_TERMS = 8
SKILL_SATURATION_K = 8


def _tokens(text) -> list[str]:
    return algo.normalize_text(text).split()


def _query_terms(profile) -> list[str]:
    terms: list[str] = []
    for r in getattr(profile, "roles", []) or []:
        terms += _tokens(r)
    for k in getattr(profile, "keywords", []) or []:
        terms += _tokens(k)
    seen: set[str] = set()
    deduped = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def bm25_coverage(query_terms: list[str], doc_terms: list[str]) -> float:
    """Bounded BM25 query coverage in [0,1]: per-term BM25 sum normalized by
    min(len(query_terms), BM25_SATURATION_TERMS), so a document matching
    ~BM25_SATURATION_TERMS distinct query tokens saturates at 1.0 regardless
    of how large the profile's full token set is. Per-term BM25 math
    (TF weighting, length normalization) is unchanged."""
    if not query_terms or not doc_terms:
        return 0.0
    s = algo.bm25_score(query_terms, doc_terms)
    denom = max(1, min(len(query_terms), BM25_SATURATION_TERMS))
    return min(1.0, s / denom)


def skill_overlap(job, profile) -> float:
    """Fraction of wanted skills found in the job's keywords, title, and
    description, normalized by min(len(want), SKILL_SATURATION_K) so a large
    production keyword list does not dilute the score: matching
    SKILL_SATURATION_K or more keywords saturates at 1.0. Neutral (0.5) when
    the profile lists no keywords."""
    want = {skill_normalize(t) for t in (getattr(profile, "keywords", []) or [])}
    want = {w for w in want if w}
    if not want:
        return 0.5
    have = {skill_normalize(t) for t in (getattr(job, "tech_stack_keywords", []) or [])}
    have |= {skill_normalize(t) for t in _tokens(f"{getattr(job, 'title', '')} {getattr(job, 'description', '')}")}
    if not have:
        return 0.0
    denom = min(len(want), SKILL_SATURATION_K)
    return min(1.0, len(have & want) / denom)


def experience_compat(job, profile) -> float:
    """1.0 when seniority is compatible, 0.0 when it contradicts, 0.5 when the
    profile does not constrain seniority."""
    want = (getattr(profile, "seniority", "") or "").lower()
    have = (getattr(job, "seniority", "") or "").lower()
    if want and have:
        return 1.0 if want in have else 0.0
    return 0.5


def location_compat(job, profile) -> float:
    """1.0 compatible, 0.0 incompatible, 0.5 unconstrained."""
    want_remote = bool(getattr(profile, "remote", True))
    job_remote = bool(getattr(job, "remote", False)) or "remote" in (
        getattr(job, "location", "") or ""
    ).lower()
    if want_remote:
        if job_remote:
            return 1.0
        # matcher.py allows on-site jobs when the profile has no location
        # requirement; score them neutral instead of 0.0 so ranking is not
        # distorted for a constraint the matcher never enforced.
        if not (getattr(profile, "location", "") or ""):
            return 0.5
        return 0.0
    want_loc = getattr(profile, "location", "") or ""
    if want_loc:
        return 1.0 if algo.location_similarity(getattr(job, "location", ""), want_loc) >= 0.5 else 0.0
    return 0.5


def score_match(job, profile) -> float:
    """Relevance score in [0,1]:

    0.60 * (0.60*BM25(title) + 0.40*BM25(description))
    + 0.20 * skill overlap
    + 0.10 * experience compatibility
    + 0.10 * location compatibility

    `matches_profile` hard rules remain authoritative and run first; BM25 only
    ranks.
    """
    query = _query_terms(profile)
    if not query:
        bm25_part = 0.5
    else:
        title_part = bm25_coverage(query, _tokens(getattr(job, "title", "") or ""))
        desc_part = bm25_coverage(query, _tokens(getattr(job, "description", "") or ""))
        bm25_part = 0.60 * title_part + 0.40 * desc_part
    skill = skill_overlap(job, profile)
    exp = experience_compat(job, profile)
    loc = location_compat(job, profile)
    total = 0.60 * bm25_part + 0.20 * skill + 0.10 * exp + 0.10 * loc
    return round(min(1.0, max(0.0, total)), 4)
