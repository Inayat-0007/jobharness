from __future__ import annotations

from jobharness.identity import (
    company_identity,
    extract_posting_id,
    location_bucket,
    normalize_title,
    title_stem,
)
from jobharness.models import Job


def make_job(source, url):
    j = Job(source_name=source, apply_url_direct=url, source_url=url)
    return j


def test_greenhouse_posting_id():
    j = make_job("greenhouse", "https://boards.greenhouse.io/acme/jobs/4123456?gh_src=abc")
    assert extract_posting_id(j) == "4123456"


def test_lever_posting_id():
    j = make_job("lever", "https://jobs.lever.co/acme/8f3c2b1a9d/apply")
    assert extract_posting_id(j) == "8f3c2b1a9d"


def test_remoteok_posting_id():
    j = make_job("remoteok", "https://remoteok.com/remote-jobs/293847-backend-engineer")
    assert extract_posting_id(j) == "293847"


def test_adzuna_posting_id():
    j = make_job("adzuna", "https://www.adzuna.com/land/ad/234567890?utm_source=x")
    assert extract_posting_id(j) == "234567890"


def test_usajobs_posting_id():
    j = make_job("usajobs", "https://www.usajobs.gov/GetJob/ViewDetails/792775400")
    assert extract_posting_id(j) == "792775400"


def test_linkedin_posting_id():
    j = make_job("linkedin", "https://www.linkedin.com/jobs/view/3987654321")
    assert extract_posting_id(j) == "3987654321"


def test_generic_identifier_field():
    j = make_job("google_jobs", "https://example.com/job/xyz")
    j.identifier = "job:abc-123"
    assert extract_posting_id(j) == "job:abc-123"


def test_no_posting_id():
    j = make_job("weworkremotely", "https://weworkremotely.com/remote-jobs/foo")
    assert extract_posting_id(j) == ""


def test_company_identity_aliases_normalize_same_entity():
    doms = set()
    names = set()
    for name in ("IBM", "IBM Corporation", "International Business Machines"):
        j = Job(company=name)
        j.apply_url_direct = "https://careers.ibm.com/jobs/1"
        cn, dom = company_identity(j)
        names.add(cn)
        doms.add(dom)
    assert names == {"international business machines"}
    assert doms == {"careers.ibm.com"}


def test_company_identity_suffix_stripping():
    j = Job(company="Acme Technologies Inc")
    j.apply_url_direct = "https://boards.greenhouse.io/acme/jobs/1"
    cn, dom = company_identity(j)
    assert cn == "acme"
    assert dom == "boards.greenhouse.io"


def test_location_buckets():
    assert location_bucket("Remote") == "remote"
    assert location_bucket("Worldwide") == "remote"
    assert location_bucket("New York, NY") == "new york ny"
    assert location_bucket("London, UK") == "london uk"
    assert location_bucket("") == ""


def test_title_helpers_delegate_to_algo():
    assert normalize_title("Senior Backend Engineer!") == "senior backend engineer"
    assert title_stem("Senior Backend Engineer") == "backend engineer"
    assert title_stem("Backend Engineer") == "backend engineer"


def test_canonical_id_levels_precedence():
    """LEVEL 1..3 outrank LEVEL 4; LEVEL 5 is the never-empty fallback.
    LEVEL 4 (company+title+location) only fires when normalize_company yields
    '' for a non-empty company (e.g. non-ASCII names)."""
    j = Job(company="日本語合同会社", title="エンジニア", location="東京")
    j.apply_url_direct = "https://example.com/j/1"
    # LEVEL 3 skipped (normalize_company("日本語合同会社") == "") -> LEVEL 4
    j.compute_hash()
    assert j.compute_canonical_id().startswith("ct:")

    j2 = Job(company="Acme", title="Engineer", location="Remote")
    j2.apply_url_direct = "https://acme.com/j/1"
    j2.canonical_url = "https://acme.com/j/1"
    # LEVEL 2 canonical URL outranks LEVEL 3/4
    assert j2.compute_canonical_id() == "url:https://acme.com/j/1"

    j3 = Job(company="Acme", title="Engineer", location="Remote")
    j3.apply_url_direct = "https://acme.com/j/1"
    # LEVEL 3 (company entity + title, location-agnostic)
    assert j3.compute_canonical_id() == "ct:acme|engineer"

    j4 = Job(company="", title="", location="")
    j4.apply_url_direct = "https://acme.com/j/1"
    j4.compute_hash()
    # LEVEL 5 fallback never empty
    assert j4.compute_canonical_id().startswith("hash:")
