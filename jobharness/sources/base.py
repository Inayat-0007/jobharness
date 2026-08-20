from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import RawJob
from ..profile import Profile


class SourceAdapter(ABC):
    name: str = ""

    @abstractmethod
    def fetch(self, profile: Profile) -> list[RawJob]:
        ...

    def enabled(self, profile: Profile) -> bool:
        return profile.sources.get(self.name, False)
