from __future__ import annotations

from jobharness.matcher import matches_profile
from jobharness.models import Job
from jobharness.profile import Profile
from jobharness.scoring.matching import (
    BM25_SATURATION_TERMS,
    SKILL_SATURATION_K,
    bm25_coverage,
    score_match,
    skill_normalize,
    skill_overlap,
)


def make_job(title="Backend Engineer", desc="python api backend", **kw):
    j = Job(title=title, description=desc)
    j.role = title
    j.remote = True
    j.location = "Remote"
    for k, v in kw.items():
        setattr(j, k, v)
    return j


def base_profile(**kw):
    p = Profile(roles=["Backend Engineer"], keywords=["python"], excludes=["java"])
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_saturation_constants():
    # Calibration constants (2026-08): denominators cap at ~8 matched
    # terms/keywords so large production profiles do not dilute scores.
    # Detailed behavior is pinned in tests/test_scoring_calibration.py.
    assert BM25_SATURATION_TERMS == 8
    assert SKILL_SATURATION_K == 8
    query = [f"t{i}" for i in range(74)]
    assert bm25_coverage(query, query[:8]) == 1.0
    # 1-keyword profile is not punished by the cap: single hit still scores.
    p = Profile(keywords=["python"])
    assert skill_overlap(make_job(desc="python api backend"), p) > 0


def test_skill_synonyms():
    assert skill_normalize("py") == "python"
    assert skill_normalize("Python") == "python"
    assert skill_normalize("node") == "nodejs"
    assert skill_normalize("JS") == "javascript"
    assert skill_normalize("c++") == "cpp"
    assert skill_normalize("aws") == "aws"


def test_score_match_range_and_ranking():
    p = base_profile()
    good = make_job(desc="python api backend engineer with python and api skills")
    poor = make_job(title="Backend Engineer", desc="go rust infrastructure")
    sg = score_match(good, p)
    sp = score_match(poor, p)
    assert 0.0 <= sg <= 1.0
    assert 0.0 <= sp <= 1.0
    assert sg > sp


def test_score_match_empty_profile():
    p = Profile()
    j = make_job()
    assert 0.0 <= score_match(j, p) <= 1.0


def test_exclusion_overrides_bm25():
    p = base_profile(excludes=["java"])
    j = make_job(title="Java Backend Engineer", desc="python django api with java spring")
    assert matches_profile(j, p) is False
    s = score_match(j, p)
    assert s > 0.5


def test_skill_overlap_empty_profile():
    p = Profile(roles=["Backend Engineer"], keywords=[])
    j = make_job()
    s = score_match(j, p)
    assert 0.0 <= s <= 1.0


def test_location_compatibility():
    j = make_job(location="New York", remote=False)
    p = base_profile(remote=False, location="New York")
    s = score_match(j, p)
    assert s > 0.5  # location compatible

    j2 = make_job(location="San Francisco", remote=False)
    s2 = score_match(j2, p)
    assert s2 < s  # location mismatch penalizes


def test_onsite_job_neutral_when_no_location_requirement():
    """matcher allows on-site jobs when profile.remote=True with no location
    requirement; score_match must not zero them out (neutral 0.5 component)."""
    from jobharness.scoring.matching import location_compat

    p = base_profile(remote=True, location="")
    j = make_job(location="New York", remote=False)
    assert matches_profile(j, p) is True
    assert location_compat(j, p) == 0.5
    j_remote = make_job(location="Remote", remote=True)
    assert location_compat(j_remote, p) == 1.0


def test_seniority_experience():
    p = base_profile(seniority="senior")
    j = make_job(seniority="senior level")
    s = score_match(j, p)
    assert s > 0.5

    j2 = make_job(seniority="junior")
    s2 = score_match(j2, p)
    assert s2 < s
