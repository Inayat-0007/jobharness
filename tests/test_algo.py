from __future__ import annotations

from jobharness import algo
from jobharness.models import CLOSED, VALID_AUTHENTIC, Job

DESC = "we are looking for a backend engineer with python api experience"


def comp(
    t1, c1, l1, d1, t2, c2, l2, d2, u1="https://acme.com/j/1", u2="https://acme.com/j/1"
):
    return algo.composite_similarity(t1, c1, l1, d1, t2, c2, l2, d2, url1=u1, url2=u2)


def test_same_job_rewritten_auto_merge():
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", DESC,
        "Backend Engineer", "Acme", "Remote", DESC,
    )
    assert verdict == "auto_merge"
    assert s == 1.0


def test_different_role_same_company_none():
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", "python api backend experience",
        "Frontend Engineer", "Acme", "Remote", "react typescript ui frontend",
        u2="https://acme.com/j/2",
    )
    assert verdict == "none"
    assert s < algo.REVIEW_THRESHOLD


def test_same_title_company_location_diff_review():
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", DESC,
        "Backend Engineer", "Acme", "New York, NY", DESC,
        u2="https://acme.com/j/2",
    )
    assert verdict == "review"
    assert algo.REVIEW_THRESHOLD <= s < algo.HIGH_THRESHOLD


def test_missing_company_review():
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", DESC,
        "Backend Engineer", "", "Remote", DESC,
        u2="",
    )
    assert verdict == "review"


def test_unrelated_jobs_none():
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", "python api",
        "Marketing Lead", "Globex", "New York", "brand campaigns growth",
        u2="https://globex.com/careers/2",
    )
    assert verdict == "none"
    assert s < 0.75


def test_backend_vs_frontend_same_company_remote_none():
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", "python api backend experience",
        "Frontend Engineer", "Acme", "Remote", "react typescript ui frontend",
        u2="https://acme.com/j/2",
    )
    assert verdict == "none"


def test_high_company_location_desc_low_title_none():
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", DESC,
        "Data Analyst", "Acme", "Remote", DESC,
        u2="https://acme.com/j/2",
    )
    assert verdict == "none"


def test_company_domain_contradiction_blocks_auto_merge():
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", DESC,
        "Backend Engineer", "Acme", "Remote", DESC,
        u1="https://acme.com/j/1", u2="https://globex.com/j/1",
    )
    assert verdict == "review"


def test_jaro_winkler_edge_cases():
    assert algo.jaro_winkler("", "") == 1.0
    assert algo.jaro_winkler("a", "") == 0.0
    assert algo.jaro_winkler("", "ab") == 0.0
    assert algo.jaro_winkler("a", "a") == 1.0
    assert algo.jaro_winkler("a", "b") == 0.0
    assert algo.jaro_winkler("ab", "a") > 0.0
    assert 0.0 <= algo.jaro_winkler("ab", "x") <= 1.0
    assert algo.jaro_winkler("Backend Engineer", "Backend Engineer") == 1.0


def test_jaro_winkler_values_rapidfuzz_independent():
    """Known-value checks that hold whether the rapidfuzz path or the
    pure-Python implementation is active (compared against expected values,
    not against each other)."""
    assert algo.jaro_winkler("", "") == 1.0
    assert algo.jaro_winkler("Python", "") == 0.0
    assert algo.jaro_winkler("Backend Engineer", "Backend Engineer") == 1.0
    assert algo.jaro_winkler("aaa", "bbb") == 0.0
    assert algo.jaro_winkler("abc", "xyz") == 0.0
    assert algo.jaro_winkler("a", "b") == 0.0


def test_company_similarity_matching_domain_strong():
    s = algo.company_similarity(
        "Acme Inc", "Acme", "acme.com", "acme.com",
        "https://acme.com/j", "https://acme.com/j",
    )
    assert s >= 0.95


def test_company_similarity_conflicting_domain_capped():
    s = algo.company_similarity(
        "Acme", "Acme", "acme.com", "globex.com",
        "https://acme.com/j", "https://globex.com/j",
    )
    assert s <= 0.55


def test_company_similarity_levenshtein_one_not_enough():
    s = algo.company_similarity("ABC", "ABX", "abc.com", "abx.com")
    assert s < 0.60
    assert algo.company_identity_pass("ABC", "ABX", "abc.com", "abx.com") is False


def test_company_similarity_unknown_domain_uncertain():
    s = algo.company_similarity("Acme", "Acme")
    assert 0.5 < s < 0.9


def test_location_similarity():
    assert algo.location_similarity("Remote", "Remote") == 1.0
    assert algo.location_similarity("Remote", "Worldwide") == 1.0
    assert algo.location_similarity("New York, NY", "New York City") == 0.5
    assert algo.location_similarity("Remote", "New York") == 0.0
    assert algo.location_similarity("", "") == 1.0


def test_description_similarity():
    assert algo.description_similarity(DESC, DESC) == 1.0
    d1 = "we are looking for a backend engineer with python api experience"
    d2 = "we are looking for a backend engineer with python api experience and strong communication skills"
    assert 0.5 < algo.description_similarity(d1, d2) < 1.0
    assert algo.description_similarity("", "") == 1.0
    assert algo.description_similarity(DESC, "") == 0.0


def test_one_sided_empty_description_renormalized():
    # Exactly one side missing a description: S_desc = 0.0, and its 0.25
    # weight is redistributed to title/company, so identical
    # title/company/location still auto-merges.
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", "",
        "Backend Engineer", "Acme", "Remote", DESC,
        u2="https://acme.com/j/2",
    )
    assert verdict == "auto_merge"
    assert s >= algo.HIGH_THRESHOLD


def test_both_empty_descriptions_auto_merge():
    # Both sides empty: no discriminating text (S_desc = 1.0); identical
    # title/company/location auto-merges.
    verdict, s = comp(
        "Backend Engineer", "Acme", "Remote", "",
        "Backend Engineer", "Acme", "Remote", "",
        u2="https://acme.com/j/2",
    )
    assert verdict == "auto_merge"
    assert s >= algo.HIGH_THRESHOLD


def test_title_stem():
    assert algo.title_stem("Backend Engineer") == "backend engineer"
    assert algo.title_stem("Senior Backend Engineer") == "backend engineer"
    assert algo.title_stem("Backend Engineer (Remote)") == "backend engineer"
    assert algo.title_stem("") == ""


def test_blocking_keys():
    job = Job(title="Senior Backend Engineer", company="Acme Inc", location="Remote")
    job.apply_url_direct = "https://acme.com/jobs/123?utm_source=x"
    job.employer_domain = "acme.com"
    keys = algo.blocking_keys(job)
    assert "acme|backend engineer" in keys
    assert "acme|remote" in keys
    assert "acme.com|backend engineer" in keys
    assert "apply:acme.com|backend engineer" in keys
    assert len(keys) == 4  # no posting_id -> external id key omitted


def test_blocking_keys_posting_id_and_missing_company():
    job = Job(title="Backend Engineer", company="", location="")
    job.posting_id = "gh_12345"
    job.employer_domain = "boards.greenhouse.io"
    keys = algo.blocking_keys(job)
    assert "gh_12345" in keys
    assert "boards.greenhouse.io|backend engineer" in keys
    assert not any(k.startswith("|") for k in keys)


def test_bm25_tf_and_length_effects():
    avgdl = 2.0
    assert algo.bm25_score(["python"], ["python"], avgdl=avgdl) > algo.bm25_score(
        ["python"], ["python", "java", "go", "c"], avgdl=avgdl
    )
    assert algo.bm25_score(["python", "python"], ["python"], avgdl=avgdl) > algo.bm25_score(
        ["python"], ["python"], avgdl=avgdl
    )


def test_bm25_idf_rare_term_scores_higher():
    idf_map = {"python": 2.0, "java": 0.5}
    assert algo.bm25_score(["python"], ["python"], idf_map=idf_map) > algo.bm25_score(
        ["java"], ["java"], idf_map=idf_map
    )
    assert algo.bm25_idf("x", 1, 100) > algo.bm25_idf("x", 50, 100)


def test_authenticity_features():
    job = Job(
        title="Backend Engineer", company="Acme", location="Remote",
        description="python api", experience_needed="5+ years",
    )
    job.apply_url_direct = "https://acme.com/jobs/1"
    job.date_posted = "2023-11-14"
    job.freshness = "fresh"
    job.employer_domain = "acme.com"
    job.authentic_status = VALID_AUTHENTIC
    job.source_authority = 5
    job.posting_id = "123"
    job.seen_sources = ["remoteok", "weworkremotely"]
    f = algo.authenticity_features(job)
    assert f["source_authority"] == 5.0
    assert f["domain_match"] == 1.0
    assert f["posting_id"] == 1.0
    assert f["http_status"] == 1.0
    assert f["freshness"] == 1.0
    assert f["completeness"] == 1.0
    assert f["cross_source"] == 1.0

    job.authentic_status = CLOSED
    f2 = algo.authenticity_features(job)
    assert f2["http_status"] == 0.0
    assert f2["closed_markers"] == 1.0


def test_description_fingerprint_stable():
    a = algo.description_fingerprint("python api backend")
    b = algo.description_fingerprint("python api backend")
    c = algo.description_fingerprint("api backend python")
    assert a == b
    assert a != c
    assert algo.description_fingerprint("") == ""
