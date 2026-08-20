from __future__ import annotations

from typing import Callable

from .models import RawJob
from .profile import Profile
from .sources.base import SourceAdapter
from .sources.api.remoteok import RemoteOKAdapter
from .sources.api.adzuna import AdzunaAdapter
from .sources.api.usajobs import USAJobsAdapter
from .sources.rss.weworkremotely import WeWorkRemotelyAdapter
from .sources.rss.remotive import RemotiveAdapter
from .sources.rss.jobicy import JobicyAdapter
from .sources.career_page.greenhouse import GreenhouseAdapter
from .sources.career_page.lever import LeverAdapter
from .sources.career_page.generic import GenericCareerPageAdapter
from .sources.google_jobs import GoogleJobsAdapter
from .sources.linkedin import LinkedInAdapter
from .sources.indeed import IndeedAdapter
from .sources.glassdoor import GlassdoorAdapter


def all_adapters() -> dict[str, SourceAdapter]:
    return {a.name: a for a in [
        RemoteOKAdapter(),
        WeWorkRemotelyAdapter(),
        RemotiveAdapter(),
        JobicyAdapter(),
        AdzunaAdapter(),
        USAJobsAdapter(),
        GreenhouseAdapter(),
        LeverAdapter(),
        GenericCareerPageAdapter(),
        GoogleJobsAdapter(),
        LinkedInAdapter(),
        IndeedAdapter(),
        GlassdoorAdapter(),
    ]}


def enabled_adapters(profile: Profile) -> list[SourceAdapter]:
    ads = all_adapters()
    return [ads[name] for name, on in profile.sources.items() if on and name in ads]
