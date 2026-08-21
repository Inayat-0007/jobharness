from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from jobharness import secrets
from jobharness.cli import build_parser, main
from jobharness.profile import Profile, save_profile, load_profile, make_demo_profile


def test_secrets_get_default():
    assert secrets.get("NONEXISTENT_VAR") == ""
    assert secrets.get("NONEXISTENT_VAR", "fallback") == "fallback"


def test_secrets_load_env_noop():
    secrets.load_env(Path("."))
    # No crash; env vars unaffected


def test_secrets_require_missing_raises():
    with pytest.raises(RuntimeError, match="Missing required env var"):
        secrets.require("NONEXISTENT_VAR")


def test_secrets_proxy_list():
    with mock.patch.dict("os.environ", {"PROXY_LIST": "http://p1:8080, http://p2:8080"}, clear=True):
        assert secrets.proxy_list() == ["http://p1:8080", "http://p2:8080"]


def test_cli_parser_run_accepts_known_args():
    p = build_parser()
    args = p.parse_args(["run", "--profile", "x.yaml", "--source", "remoteok", "--top", "5", "--no-llm"])
    assert args.command == "run"
    assert args.profile == "x.yaml"
    assert args.sources == ["remoteok"]
    assert args.top == 5
    assert args.no_llm is True


def test_cli_parser_dashboard_accepts_args():
    p = build_parser()
    args = p.parse_args(["dashboard", "--reports", "/tmp/r", "--out", "/tmp/d.html"])
    assert args.command == "dashboard"
    assert args.reports == "/tmp/r"
    assert args.out == "/tmp/d.html"


def test_profile_save_roundtrip(tmp_path):
    original = Profile(
        name="test",
        roles=["Backend Engineer"],
        keywords=["python"],
        excludes=["manager"],
        location="Remote",
        remote=True,
        seniority="mid",
        llm_provider="gemini",
        top_n=30,
        adzuna_country="in",
        sources={"remoteok": True, "greenhouse": True},
    )
    path = tmp_path / "p.yaml"
    save_profile(original, path)
    loaded = load_profile(path)
    assert loaded.name == original.name
    assert loaded.roles == original.roles
    assert loaded.keywords == original.keywords
    assert loaded.excludes == original.excludes
    assert loaded.location == original.location
    assert loaded.remote == original.remote
    assert loaded.seniority == original.seniority
    assert loaded.top_n == original.top_n
    assert loaded.adzuna_country == original.adzuna_country
    assert loaded.sources["remoteok"] is True
    assert loaded.sources["greenhouse"] is True


def test_make_demo_profile(tmp_path):
    path = tmp_path / "demo.yaml"
    prof = make_demo_profile(path)
    assert path.exists()
    assert prof.name == "demo"
    assert "Backend Engineer" in prof.roles


def test_load_profile_merges_default_sources(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("name: t\nroles: [Engineer]\nkeywords: []\nexcludes: []\n", encoding="utf-8")
    prof = load_profile(path)
    assert prof.sources["remoteok"] is True  # from defaults
    assert prof.remote is True  # default


def test_load_profile_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_profile("/nonexistent/profile.yaml")