"""V3 P1 accuracy tests: LLM consistency gate, salary normalization,
posting-ID extraction for the new India sources, and Indian company suffixes.
"""
from __future__ import annotations

from jobharness import algo, extractor
from jobharness.identity import extract_posting_id
from jobharness.matcher import _normalize_salary_to_annual, matches_profile
from jobharness.models import Job, RawJob


def make_raw(**kw):
    base = dict(
        source_name="test",
        source_url="https://example.com/j/1",
        title="Backend Engineer",
    )
    base.update(kw)
    return RawJob(**base)


def fake_llm(raw, fields):
    """Return a RawJob + Job pair with the LLM monkeypatched to `fields`."""
    import json

    job = Job()
    _apply = {}

    class _Fake:
        @staticmethod
        def complete(prompt, **kw):
            return json.dumps(fields)

        @staticmethod
        def extract_json(text):
            return extractor.llm.extract_json(text)

    return raw, job, _Fake


# ---------------------------------------------------------------------------
# LLM consistency gate
# ---------------------------------------------------------------------------


def test_consistent_substring_and_tokens():
    assert extractor._consistent("Acme Corp", "Acme Corp is hiring") is True
    assert extractor._consistent("acme corp", "ACME CORP IS HIRING") is True
    assert extractor._consistent("Acme", "We are Acme Corp") is True
    # "corp" appears but "evil" does not -> 50% token overlap < 80%
    assert extractor._consistent("Evil Corp", "Acme Corp is hiring") is False
    assert extractor._consistent("", "anything") is False
    assert extractor._consistent("anything", "") is False


def test_llm_hallucinated_company_kept_source(monkeypatch):
    raw = make_raw(
        company="Acme",
        description="We build scalable Python APIs with Django.",
        posted_date="2023-11-14",
    )
    llm_out = (
        '{"role":"Backend Engineer","title":"Backend Engineer","company":"Evil Corp",'
        '"location":"MISSING","experience_needed":"MISSING","date_posted":"2023-11-14",'
        '"salary_if_present":"MISSING","seniority":"MISSING","tech_stack_keywords":[]}'
    )
    monkeypatch.setattr(extractor.llm, "complete", lambda *a, **k: llm_out)
    job = extractor.extract(raw, use_llm=True)
    assert job.company == "Acme"  # hallucination rejected, source truth kept


def test_llm_value_found_in_description_adopted(monkeypatch):
    raw = make_raw(
        company="Acme",
        description="Python Backend Engineer role: build APIs with Django.",
        posted_date="2023-11-14",
    )
    llm_out = (
        '{"role":"Backend Engineer","title":"Python Backend Engineer","company":"Acme",'
        '"location":"Remote","experience_needed":"MISSING","date_posted":"2023-11-14",'
        '"salary_if_present":"MISSING","seniority":"MISSING","tech_stack_keywords":["python"]}'
    )
    monkeypatch.setattr(extractor.llm, "complete", lambda *a, **k: llm_out)
    job = extractor.extract(raw, use_llm=True)
    assert job.title == "Python Backend Engineer"  # grounded in description


def test_llm_missing_keeps_source_value(monkeypatch):
    raw = make_raw(
        company="Acme",
        description="Python backend role.",
        posted_date="2023-11-14",
    )
    llm_out = (
        '{"role":"Backend Engineer","title":"MISSING","company":"MISSING",'
        '"location":"MISSING","experience_needed":"MISSING","date_posted":"MISSING",'
        '"salary_if_present":"MISSING","seniority":"MISSING","tech_stack_keywords":[]}'
    )
    monkeypatch.setattr(extractor.llm, "complete", lambda *a, **k: llm_out)
    job = extractor.extract(raw, use_llm=True)
    assert job.title == "Backend Engineer"
    assert job.company == "Acme"
    assert job.date_posted == "2023-11-14"


def test_llm_hallucinated_date_rejected(monkeypatch):
    raw = make_raw(
        company="Acme",
        description="Python backend role with Django and PostgreSQL.",
        posted_date="2023-11-14",
    )
    llm_out = (
        '{"role":"Backend Engineer","title":"Backend Engineer","company":"Acme",'
        '"location":"MISSING","experience_needed":"MISSING","date_posted":"2024-05-05",'
        '"salary_if_present":"MISSING","seniority":"MISSING","tech_stack_keywords":[]}'
    )
    monkeypatch.setattr(extractor.llm, "complete", lambda *a, **k: llm_out)
    job = extractor.extract(raw, use_llm=True)
    assert job.date_posted == "2023-11-14"  # 2024-05-05 is not in the source


def test_llm_equivalent_date_format_accepted(monkeypatch):
    raw = make_raw(
        company="Acme",
        description="Python backend role.",
        posted_date="2023-11-14",
    )
    llm_out = (
        '{"role":"Backend Engineer","title":"Backend Engineer","company":"Acme",'
        '"location":"MISSING","experience_needed":"MISSING","date_posted":"14 Nov 2023",'
        '"salary_if_present":"MISSING","seniority":"MISSING","tech_stack_keywords":[]}'
    )
    monkeypatch.setattr(extractor.llm, "complete", lambda *a, **k: llm_out)
    job = extractor.extract(raw, use_llm=True)
    assert job.date_posted == "2023-11-14"  # same date, different format


def test_tech_stack_keywords_union_not_overwrite(monkeypatch):
    raw = make_raw(
        company="Acme",
        description="Python developer with Django and PostgreSQL experience.",
        posted_date="2023-11-14",
    )
    llm_out = (
        '{"role":"Backend Engineer","title":"Backend Engineer","company":"Acme",'
        '"location":"MISSING","experience_needed":"MISSING","date_posted":"2023-11-14",'
        '"salary_if_present":"MISSING","seniority":"MISSING","tech_stack_keywords":["python"]}'
    )
    monkeypatch.setattr(extractor.llm, "complete", lambda *a, **k: llm_out)
    job = extractor.extract(raw, use_llm=True)
    assert "python" in job.tech_stack_keywords
    assert "django" in job.tech_stack_keywords
    assert "postgresql" in job.tech_stack_keywords


# ---------------------------------------------------------------------------
# Salary normalization
# ---------------------------------------------------------------------------


def test_salary_normalize_lpa():
    assert _normalize_salary_to_annual("₹12-18 LPA") == 1_800_000
    assert _normalize_salary_to_annual("₹ 6 - 8 LPA") == 800_000
    assert _normalize_salary_to_annual("6-8 LPA") == 800_000
    assert _normalize_salary_to_annual("₹ 8 LPA CTC") == 800_000


def test_salary_normalize_units():
    assert _normalize_salary_to_annual("₹40,000/month") == 480_000
    assert _normalize_salary_to_annual("₹ 40,000 per month") == 480_000
    assert _normalize_salary_to_annual("₹ 5000 per hour") == 10_000_000
    assert _normalize_salary_to_annual("₹ 5000 hourly") == 10_000_000
    assert _normalize_salary_to_annual("1 crore") == 10_000_000
    assert _normalize_salary_to_annual("₹ 1.2 lakh") == 120_000


def test_salary_normalize_usd_kept_raw_numeric():
    # "$100K" is 100,000 as a raw number; no currency conversion (INR floor).
    assert _normalize_salary_to_annual("$100K") == 100_000
    assert _normalize_salary_to_annual("$120k-$150k") == 150_000


def test_salary_normalize_bare_numbers():
    assert _normalize_salary_to_annual("80000") == 80_000
    assert _normalize_salary_to_annual("120000-150000") == 150_000
    # small bare numbers (experience years) are ignored
    assert _normalize_salary_to_annual("5+ years experience") is None


def test_salary_normalize_absent():
    assert _normalize_salary_to_annual("") is None
    assert _normalize_salary_to_annual(None) is None
    assert _normalize_salary_to_annual("MISSING") is None
    assert _normalize_salary_to_annual("Not disclosed") is None


def test_salary_floor_uses_annualized_value():
    p = base_profile(salary_floor=1_000_000)  # 10 LPA floor
    j = make_job()
    j.salary_if_present = "₹ 8 LPA"
    assert matches_profile(j, p) is False
    j.salary_if_present = "₹ 12 LPA"
    assert matches_profile(j, p) is True
    # low monthly salary annualizes below the floor
    j.salary_if_present = "₹ 30,000 per month"
    assert matches_profile(j, p) is False


def test_salary_floor_absent_salary_passes():
    p = base_profile(salary_floor=1_000_000)
    j = make_job()
    j.salary_if_present = ""
    assert matches_profile(j, p) is True
    j.salary_if_present = "Not disclosed"
    assert matches_profile(j, p) is True


# ---------------------------------------------------------------------------
# Posting-ID extraction (new sources)
# ---------------------------------------------------------------------------


def make_posting_job(source, url):
    j = Job(source_name=source, apply_url_direct=url, source_url=url)
    return j


def test_posting_id_naukri():
    j = make_posting_job("naukri", "https://www.naukri.com/job/backend-engineer-5081223456?src=cluster")
    assert extract_posting_id(j) == "5081223456"
    j = make_posting_job("naukri", "https://www.naukri.com/job-listings-python-developer-508122345678")
    assert extract_posting_id(j) == "508122345678"


def test_posting_id_hirist():
    j = make_posting_job("hirist", "https://www.hirist.com/job/python-developer-23761459")
    assert extract_posting_id(j) == "23761459"
    j = make_posting_job("hirist", "https://hirist.tech/j/23761459")
    assert extract_posting_id(j) == "23761459"


def test_posting_id_internshala():
    j = make_posting_job(
        "internshala",
        "https://internshala.com/internship/detail/python-internship-at-acme-2025-2024111234567",
    )
    assert extract_posting_id(j) == "2024111234567"
    j = make_posting_job(
        "internshala",
        "https://internshala.com/internship/detail/ml-internship-at-zeta-2025-abcdef1234567890",
    )
    assert extract_posting_id(j) == "abcdef1234567890"


def test_posting_id_wellfound():
    j = make_posting_job("wellfound", "https://wellfound.com/jobs/2987431?source=search")
    assert extract_posting_id(j) == "2987431"
    j = make_posting_job("wellfound", "https://angel.co/company/acme/jobs/2987431")
    assert extract_posting_id(j) == "2987431"


def test_posting_id_indeed():
    j = make_posting_job("indeed", "https://in.indeed.com/viewjob?jk=1a2b3c4d5e6f7a8b")
    assert extract_posting_id(j) == "1a2b3c4d5e6f7a8b"


def test_posting_id_glassdoor():
    j = make_posting_job(
        "glassdoor",
        "https://www.glassdoor.com/job/backend-engineer-jobs-JOB_IL.0,15_IC2934127_KE23,38.htm?jl=1009167832649",
    )
    assert extract_posting_id(j) == "1009167832649"


def test_posting_id_google_jobs():
    j = make_posting_job("google_jobs", "https://www.google.com/search?q=python+jobs&ibp=htl;jobs&jid=job-abc:123")
    assert extract_posting_id(j) == "job-abc:123"
    j = make_posting_job("google_jobs", "https://www.google.com/search?q=python&htidocid=htidocid-abc123")
    assert extract_posting_id(j) == "htidocid-abc123"


def test_posting_id_rss_sources():
    j = make_posting_job("remotive", "https://remotive.com/remote-jobs/software-dev/python-developer-123456")
    assert extract_posting_id(j) == "123456"
    j = make_posting_job("weworkremotely", "https://weworkremotely.com/remote-jobs/7654321-senior-backend-engineer")
    assert extract_posting_id(j) == "7654321"


def test_posting_id_no_false_positive_on_search_urls():
    j = make_posting_job("naukri", "https://www.naukri.com/mnjuser/search?q=python+fresher&l=India")
    assert extract_posting_id(j) == ""
    j = make_posting_job("weworkremotely", "https://weworkremotely.com/remote-jobs/foo")
    assert extract_posting_id(j) == ""


# ---------------------------------------------------------------------------
# Indian company suffixes
# ---------------------------------------------------------------------------


def test_normalize_company_indian_suffixes():
    assert algo.normalize_company("Acme Pvt Ltd") == "acme"
    assert algo.normalize_company("Acme Pvt. Ltd.") == "acme"
    assert algo.normalize_company("Acme Private Limited") == "acme"
    assert algo.normalize_company("Zeta LLP") == "zeta"
    assert algo.normalize_company("Acme Limited") == "acme"
    assert algo.normalize_company("Acme Technologies Pvt Ltd") == "acme"


def test_normalize_company_existing_suffixes_kept():
    assert algo.normalize_company("Acme Inc") == "acme"
    assert algo.normalize_company("Acme Corporation") == "acme"
    assert algo.normalize_company("IBM") == "ibm"


def test_company_domain_hint_indian_suffixes():
    assert algo.company_domain_hint("Acme Pvt Ltd") == "acme"
    assert algo.company_domain_hint("Zeta LLP") == "zeta"


# ---------------------------------------------------------------------------
# helpers (mirror tests/test_matcher.py)
# ---------------------------------------------------------------------------


def make_job(title="Backend Engineer", company="Acme", location="Remote", desc="python api backend"):
    j = Job(title=title, company=company, location=location)
    j.role = title
    j.description = desc
    j.tech_stack_keywords = []
    j.remote = "remote" in location.lower()
    return j


def base_profile(**kw):
    from jobharness.profile import Profile

    p = Profile(roles=["Backend Engineer"], keywords=["python"], excludes=["manager"])
    for k, v in kw.items():
        setattr(p, k, v)
    return p
