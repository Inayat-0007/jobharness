from __future__ import annotations

from .authenticity import authenticity_score
from .decision import decide
from .matching import score_match, skill_normalize
from .thresholds import (
    AUTO_ACCEPT,
    AUTO_ACCEPT_AUTHENTICITY,
    AUTO_ACCEPT_IDENTITY,
    AUTO_ACCEPT_MATCH,
    MEDIUM_AUTHENTICITY,
    MIN_UNCERTAIN_IDENTITY,
    REJECT,
    REVIEW,
    REVIEW_MATCH,
    STATE_CLOSED,
    STATE_EXCLUDED,
    STATE_INVALID_URL,
    STATE_OPEN,
)

__all__ = [
    "authenticity_score",
    "score_match",
    "skill_normalize",
    "decide",
    "AUTO_ACCEPT",
    "AUTO_ACCEPT_AUTHENTICITY",
    "AUTO_ACCEPT_IDENTITY",
    "AUTO_ACCEPT_MATCH",
    "MEDIUM_AUTHENTICITY",
    "MIN_UNCERTAIN_IDENTITY",
    "REJECT",
    "REVIEW",
    "REVIEW_MATCH",
    "STATE_CLOSED",
    "STATE_EXCLUDED",
    "STATE_INVALID_URL",
    "STATE_OPEN",
]
