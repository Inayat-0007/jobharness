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
