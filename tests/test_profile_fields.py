from __future__ import annotations

from jobharness.profile import Profile, load_profile, save_profile


def test_profile_default_fields(tmp_path):
    p = Profile()
    assert p.date_format == "DMY"
    assert p.timeout_minutes == 60
    assert p.enrich_cap == 50
    assert p.browser_career_workers == 4
    assert p.max_pages == 1
    assert p.career_fetch_workers == 4


def test_profile_save_round_trips_all_fields(tmp_path):
    original = Profile(
        name="test",
        roles=["Engineer"],
        keywords=["python"],
        date_format="MDY",
        timeout_minutes=30,
        enrich_cap=10,
        browser_career_workers=2,
        max_pages=3,
        career_fetch_workers=8,
    )
    path = tmp_path / "p.yaml"
    save_profile(original, path)
    loaded = load_profile(path)
    assert loaded.date_format == original.date_format
    assert loaded.timeout_minutes == original.timeout_minutes
    assert loaded.enrich_cap == original.enrich_cap
    assert loaded.browser_career_workers == original.browser_career_workers
    assert loaded.max_pages == original.max_pages
    assert loaded.career_fetch_workers == original.career_fetch_workers


def test_profile_save_ignores_null_fields(tmp_path):
    p = Profile(date_format="MDY", timeout_minutes=0, enrich_cap=99)
    path = tmp_path / "p2.yaml"
    save_profile(p, path)
    loaded = load_profile(path)
    assert loaded.date_format == "MDY"
    assert loaded.timeout_minutes == 0
    assert loaded.enrich_cap == 99
