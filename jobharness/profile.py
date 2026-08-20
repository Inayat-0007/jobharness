from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

import yaml


@dataclass
class Profile:
    name: str = "default"
    roles: list = field(default_factory=list)          # e.g. ["Backend Engineer"]
    keywords: list = field(default_factory=list)      # must-have keywords
    excludes: list = field(default_factory=list)      # exclude if present in title/desc
    location: str = ""
    remote: bool = True
    seniority: str = ""                                # e.g. "mid", "senior", "junior"
    salary_floor: Optional[int] = None
    company_allowlist: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)        # {source_name: bool}
    llm_provider: str = "gemini"
    top_n: int = 50


def default_sources() -> dict:
    return {
        "remoteok": True,
        "weworkremotely": True,
        "remotive": True,
        "jobicy": True,
        "adzuna": True,
        "usajobs": True,
        "greenhouse": True,
        "lever": True,
        "google_jobs": True,
        "linkedin": False,
        "indeed": False,
        "glassdoor": False,
    }


def load_profile(path: str | Path) -> Profile:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Profile not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data = dict(raw)
    if "sources" not in data:
        data["sources"] = default_sources()
    else:
        merged = default_sources()
        merged.update(data["sources"])
        data["sources"] = merged
    if "remote" not in data:
        data["remote"] = True
    return Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__})


def save_profile(profile: Profile, path: str | Path) -> None:
    p = Path(path)
    data = {
        "name": profile.name,
        "roles": profile.roles,
        "keywords": profile.keywords,
        "excludes": profile.excludes,
        "location": profile.location,
        "remote": profile.remote,
        "seniority": profile.seniority,
        "salary_floor": profile.salary_floor,
        "company_allowlist": profile.company_allowlist,
        "sources": profile.sources,
        "llm_provider": profile.llm_provider,
        "top_n": profile.top_n,
    }
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def make_demo_profile(path: str | Path) -> Profile:
    prof = Profile(
        name="demo",
        roles=["Backend Engineer", "Software Engineer"],
        keywords=["python", "api", "backend"],
        excludes=["manager", "director", "c++"],
        location="",
        remote=True,
        seniority="mid",
        llm_provider="gemini",
        top_n=50,
    )
    save_profile(prof, path)
    return prof
