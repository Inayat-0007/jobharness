from __future__ import annotations

from abc import ABC, abstractmethod

from ..browser import detect_block
from ..models import RawJob
from ..profile import Profile
from .exceptions import BlockedError, SourceDownError


class SourceAdapter(ABC):
    name: str = ""

    @abstractmethod
    def fetch(self, profile: Profile) -> list[RawJob]:
        ...

    def enabled(self, profile: Profile) -> bool:
        return profile.sources.get(self.name, False)


def raise_navigation_failure(name: str, page, goto_err: Exception) -> None:
    """Classify a failed page navigation once the mobile fallback has retried.

    Browser adapters call this when ``page.goto`` raised and the page produced
    no job data: a block wall rendered during the failed load is BLOCKED,
    everything else is a transport failure (SOURCE_DOWN). The runner records
    the matching SourceStatus instead of a silent empty result.
    """
    if detect_block(page):
        raise BlockedError(f"{name}: blocked after failed navigation")
    raise SourceDownError(f"{name}: navigation failed: {goto_err}")
