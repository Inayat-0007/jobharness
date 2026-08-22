from __future__ import annotations

from jobharness.matcher import matches_profile
from jobharness.models import Job
from jobharness.profile import Profile


def make_job(title="Backend Engineer", company="Acme", location="Remote", desc="python api backend"):
    j = Job(title=title, company=company, location=location)
    j.role = title
    j.description = desc
    j.tech_stack_keywords = []
    j.remote = "remote" in location.lower()
    return j


def base_profile(**kw):
    p = Profile(roles=["Backend Engineer"], keywords=["python"], excludes=["manager"])
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_excludes_rejects_manager():
    assert matches_profile(make_job(title="Engineering Manager"), base_profile()) is False


def test_keyword_required():
    assert matches_profile(make_job(desc="java spring"), base_profile()) is False
    assert matches_profile(make_job(desc="python django"), base_profile()) is True


def test_role_match_on_title():
    assert matches_profile(make_job(title="Backend Engineer"), base_profile()) is True


def test_role_not_present_rejects():
    assert matches_profile(make_job(title="Marketing Lead", desc="python"), Profile(roles=["Backend Engineer"], keywords=["python"], excludes=[])) is False


def test_seniority_filter():
    p = base_profile(seniority="senior")
    j = make_job()
    j.seniority = "junior"
    assert matches_profile(j, p) is False
    j.seniority = "senior level"
    assert matches_profile(j, p) is True


def test_salary_floor_rejects_below():
    p = base_profile(salary_floor=100000)
    j = make_job()
    j.salary_if_present = "80000"
    assert matches_profile(j, p) is False
    j.salary_if_present = "120000-150000"
    assert matches_profile(j, p) is True


def test_location_india_rejects_remote_and_foreign():
    p = base_profile(location="India", remote=False)
    assert matches_profile(make_job(title="Backend Engineer", location="Remote", desc="python"), p) is False
    assert matches_profile(make_job(title="Backend Engineer", location="United States", desc="python"), p) is False
    assert matches_profile(make_job(title="Backend Engineer", location="Bengaluru, Karnataka, India", desc="python"), p) is True
    assert matches_profile(make_job(title="Backend Engineer", location="Bangalore, Karnataka", desc="python"), p) is True
    assert matches_profile(make_job(title="Backend Engineer", location="Hyderabad, Telangana", desc="python"), p) is True


def test_location_india_allows_unknown():
    p = base_profile(location="India")
    assert matches_profile(make_job(title="Backend Engineer", location="", desc="python"), p) is True


def test_location_remote_allowed_when_profile_remote():
    p = base_profile(location="India", remote=True)
    assert matches_profile(make_job(title="Backend Engineer", location="Remote", desc="python"), p) is True


def test_empty_description_without_keyword_or_role_rejected():
    # Deliberate change: an empty description must NOT bypass the keyword gate.
    p = base_profile(keywords=["python"], roles=["Backend Engineer"])
    j = make_job(title="Marketing Lead", company="Acme", desc="")
    assert matches_profile(j, p) is False


def test_empty_description_keyword_in_title_accepted():
    p = base_profile(keywords=["python"], roles=["Backend Engineer"])
    j = make_job(title="Backend Engineer (Python)", company="Acme", desc="")
    assert matches_profile(j, p) is True


def test_empty_description_role_in_title_accepted():
    p = base_profile(keywords=["python"], roles=["Backend Engineer"])
    j = make_job(title="Backend Engineer", company="Acme", desc="")
    assert matches_profile(j, p) is True


def test_empty_description_keyword_in_company_accepted():
    p = base_profile(keywords=["python"], roles=[])
    j = make_job(title="Developer", company="Python Corp", desc="")
    assert matches_profile(j, p) is True


def test_empty_description_keyword_in_tech_stack_accepted():
    p = base_profile(keywords=["python"], roles=[])
    j = make_job(title="Developer", company="Acme", desc="")
    j.tech_stack_keywords = ["python"]
    assert matches_profile(j, p) is True


def test_compiled_patterns_cached_on_profile():
    p = base_profile()
    assert matches_profile(make_job(), p) is True
    cached = getattr(p, "_compiled_patterns", None)
    assert cached is not None
    assert set(cached) == {"roles", "keywords", "excludes"}
    assert matches_profile(make_job(title="Marketing Lead", desc="java spring"), p) is False
    assert p._compiled_patterns is cached


def test_exclude_cpp_terms_match():
    def _job(title="Backend Engineer", desc="", company="Acme", location="Remote"):
        j = Job(title=title, company=company, location=location)
        j.role = title
        j.description = desc
        j.tech_stack_keywords = []
        j.remote = "remote" in location.lower()
        return j

    def _profile(**kw):
        p = Profile(roles=[], keywords=[], excludes=["c++"])
        for k, v in kw.items():
            setattr(p, k, v)
        return p

    # C++ jobs must be rejected
    assert matches_profile(_job(title="C++ Developer"), _profile()) is False
    assert matches_profile(_job(title="C++11 Developer"), _profile()) is False
    assert matches_profile(_job(title="C++/Qt Developer"), _profile()) is False
    # Non-C++ jobs must NOT be rejected by the c++ exclude
    assert matches_profile(_job(title="Customer Success Manager"), _profile()) is True
    assert matches_profile(_job(title="Python Developer"), _profile()) is True


def test_exclude_pa_and_csharp_terms():
    def _job(title="Backend Engineer", desc="", company="Acme", location="Remote"):
        j = Job(title=title, company=company, location=location)
        j.role = title
        j.description = desc
        j.tech_stack_keywords = []
        j.remote = "remote" in location.lower()
        return j

    def _profile(excludes, **kw):
        p = Profile(roles=[], keywords=[], excludes=excludes)
        for k, v in kw.items():
            setattr(p, k, v)
        return p

    # p.a. exclude: "12 LPA p.a." description rejected
    assert matches_profile(
        _job(title="Developer", desc="salary 12 LPA p.a. with benefits"),
        _profile(excludes=["p.a."]),
    ) is False
    # "LPA" alone (no "p.a.") must NOT be falsely excluded
    assert matches_profile(
        _job(title="Developer", desc="salary 12 LPA"),
        _profile(excludes=["p.a."]),
    ) is True
    # c# exclude
    assert matches_profile(
        _job(title="C# Developer"),
        _profile(excludes=["c#"]),
    ) is False
