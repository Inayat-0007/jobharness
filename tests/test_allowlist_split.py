from __future__ import annotations

from jobharness.matcher import matches_profile
from jobharness.models import Job
from jobharness.profile import Profile, load_profile


def _profile(**kw):
    p = Profile(roles=["Engineer"])
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def _gh_job(company="Airbnb"):
    j = Job(title="Engineer", company=company, location="Remote")
    j.role = "Engineer"
    j.description = "python"
    j.remote = True
    j.source_name = "greenhouse"
    return j


def test_greenhouse_board_slug_enforced(tmp_path):
    # greenhouse_boards restricts Greenhouse jobs to those companies.
    p = _profile(greenhouse_boards=["airbnb", "stripe"])
    assert matches_profile(_gh_job("Airbnb"), p) is True
    assert matches_profile(_gh_job("Unknown Co"), p) is False


def test_career_pages_company_enforced():
    p = _profile(career_pages=[{"company": "Notion", "url": "https://notion.so/careers"}])
    g = _gh_job("Notion")
    g.source_name = "career_page_generic"
    assert matches_profile(g, p) is True
    g2 = _gh_job("Some Startup")
    g2.source_name = "career_page_generic"
    assert matches_profile(g2, p) is False


def test_legacy_company_allowlist_still_feeds_greenhouse_and_lever(tmp_path):
    pth = tmp_path / "p.yaml"
    pth.write_text(
        "name: legacy\nroles: [Engineer]\nkeywords: []\nexcludes: []\nremote: true\n"
        "company_allowlist:\n  - airbnb\nsources:\n  remoteok: false\n",
        encoding="utf-8",
    )
    p = load_profile(pth)
    # migration should have moved string "airbnb" into greenhouse+lever boards.
    assert p.greenhouse_boards == ["airbnb"]
    assert p.lever_boards == ["airbnb"]
    assert matches_profile(_gh_job("Airbnb"), p) is True


def test_no_allowlist_means_no_company_restriction():
    p = _profile()  # empty allowlists
    assert matches_profile(_gh_job("Anyone"), p) is True


def test_aggregator_sources_not_restricted_by_boards():
    p = _profile(greenhouse_boards=["airbnb"])
    j = _gh_job("Anyone")
    j.source_name = "remoteok"
    assert matches_profile(j, p) is True  # remoteok not gated by greenhouse boards


def test_allowlist_matches_whole_word_not_substring():
    p = _profile(greenhouse_boards=["airbnb"])
    # 'Airbnbish' must NOT pass: 'airbnb' is a substring but not a word token.
    assert matches_profile(_gh_job("Airbnbish Co"), p) is False
    # Multi-word company with the allowed slug as one token still matches.
    assert matches_profile(_gh_job("Airbnb Inc."), p) is True


def test_company_allowlist_cached_on_profile():
    p = _profile(greenhouse_boards=["airbnb", "stripe"])
    assert matches_profile(_gh_job("Airbnb"), p) is True
    cached = getattr(p, "_allowed_companies", None)
    assert cached == {"airbnb", "stripe"}
    assert matches_profile(_gh_job("Stripe"), p) is True
    assert p._allowed_companies is cached
