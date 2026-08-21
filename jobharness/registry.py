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
from .sources.career_page.browser_generic import CareerPageBrowserAdapter
from .sources.google_jobs import GoogleJobsAdapter
from .sources.linkedin import LinkedInAdapter
from .sources.linkedin_guest import LinkedInGuestAdapter
from .sources.indeed import IndeedAdapter
from .sources.glassdoor import GlassdoorAdapter
from .sources.naukri import NaukriAdapter
from .sources.internshala import InternshalaAdapter
from .sources.hirist import HiristAdapter
from .sources.wellfound import WellfoundAdapter


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
        CareerPageBrowserAdapter(),
        GoogleJobsAdapter(),
        LinkedInAdapter(),
        LinkedInGuestAdapter(),
        IndeedAdapter(),
        GlassdoorAdapter(),
        NaukriAdapter(),
        InternshalaAdapter(),
        HiristAdapter(),
        WellfoundAdapter(),
    ]}


def enabled_adapters(profile: Profile) -> list[SourceAdapter]:
    ads = all_adapters()
    return [ads[name] for name, on in profile.sources.items() if on and name in ads]
