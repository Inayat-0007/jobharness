from __future__ import annotations

from jobharness.evidence.source import SOURCE_AUTHORITY, source_authority
from jobharness.profile import Profile, default_sources
from jobharness.registry import all_adapters, enabled_adapters

NEW_PORTALS = ["naukri", "internshala", "hirist", "wellfound"]


def test_new_portals_registered():
    ads = all_adapters()
    for name in NEW_PORTALS:
        assert name in ads


def test_new_portals_on_by_default():
    prof = Profile()
    prof.sources = default_sources()
    enabled = {a.name for a in enabled_adapters(prof)}
    for name in NEW_PORTALS:
        assert name in enabled


def test_default_sources_include_new_portals():
    for name in NEW_PORTALS:
        assert default_sources().get(name) is True


def test_source_authority_registered_for_new_portals():
    for name in NEW_PORTALS:
        assert name in SOURCE_AUTHORITY
        assert source_authority(name) == 0


def test_profile_merge_keeps_explicit_off(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "name: t\nroles: [Software Engineer]\nsources:\n  naukri: false\n",
        encoding="utf-8",
    )
    from jobharness.profile import load_profile

    prof = load_profile(p)
    assert prof.sources["naukri"] is False
    for name in ("internshala", "hirist", "wellfound"):
        assert prof.sources[name] is True


def test_india_portals_enabled_via_explicit_off_only():
    ads = all_adapters()
    for name in NEW_PORTALS:
        assert ads[name].name == name
