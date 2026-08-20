from __future__ import annotations

from jobharness.models import Job
from jobharness.profile import Profile
from jobharness.matcher import matches_profile
from jobharness.scoring.matching import score_match, skill_normalize


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


def test_seniority_experience():
    p = base_profile(seniority="senior")
    j = make_job(seniority="senior level")
    s = score_match(j, p)
    assert s > 0.5

    j2 = make_job(seniority="junior")
    s2 = score_match(j2, p)
    assert s2 < s