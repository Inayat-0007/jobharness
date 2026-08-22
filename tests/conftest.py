"""Shared pytest fixtures and marker registration (V3 WS-6)."""

from __future__ import annotations

import pytest

from jobharness.models import VALID_AUTHENTIC, Job

_MARKERS = {
    "browser": "tests requiring a real browser (excluded from CI)",
    "ml": "tests requiring the ml extra (scikit-learn)",
    "integration": "tests requiring live network access",
}

_ENV_VARS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_BASE_URL",
    "GEMINI_MODEL",
    "GLM_API_KEY",
    "GLM_BASE_URL",
    "GLM_MODEL",
    "QWEN_API_KEY",
    "QWEN_BASE_URL",
    "QWEN_MODEL",
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
    "NVIDIA_MODEL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "ADZUNA_APP_KEY",
    "USAJOBS_API_KEY",
    "PROXY_LIST",
    "BROWSER_USER_DATA_DIR",
    "COOKIE_DIR",
)


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so ``pytest -m`` never warns about unknown ones."""
    for name, description in _MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {description}")


@pytest.fixture
def tmp_profile(tmp_path):
    """Write a minimal valid profile YAML into tmp_path and return its path.

    Mirrors tests/profiles/test_demo.yaml; missing keys merge with
    profile.default_sources() on load.
    """
    import yaml

    data = {
        "name": "demo",
        "roles": ["Backend Engineer"],
        "keywords": ["python"],
        "excludes": ["manager"],
        "location": "",
        "remote": True,
        "seniority": "",
        "salary_floor": None,
        "company_allowlist": [],
        "sources": {
            "remoteok": True,
            "weworkremotely": True,
            "remotive": False,
            "jobicy": False,
            "adzuna": False,
            "usajobs": False,
            "greenhouse": False,
            "lever": False,
            "career_page_generic": False,
            "google_jobs": False,
            "linkedin": False,
            "indeed": False,
            "glassdoor": False,
        },
        "llm_provider": "gemini",
        "top_n": 50,
    }
    path = tmp_path / "test_profile.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def clear_env(monkeypatch):
    """Remove every jobharness-relevant env var so tests never read .env."""
    for key in _ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    return None


@pytest.fixture
def sample_job() -> Job:
    """A known-good jobharness.models.Job with recognizable fields."""
    job = Job(
        role="Backend Engineer",
        title="Backend Engineer",
        company="Acme Corp",
        location="Bangalore, India",
        remote=False,
        description="Build scalable Python APIs with Django and PostgreSQL.",
        apply_url_direct="https://acme.example.com/jobs/backend-engineer",
        source_url="https://acme.example.com/careers",
        source_name="greenhouse",
        posting_id="gh-12345",
        authentic_status=VALID_AUTHENTIC,
    )
    job.compute_hash()
    return job
