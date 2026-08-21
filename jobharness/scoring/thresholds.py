from __future__ import annotations

# Centralized thresholds (plan 3.2). Never scatter these numbers in
# runner/verify/matcher; Phase 4 benchmark tunes them from labeled data.
AUTO_ACCEPT_IDENTITY = 0.95
AUTO_ACCEPT_AUTHENTICITY = 70
AUTO_ACCEPT_MATCH = 0.60
REVIEW_MATCH = 0.40
MEDIUM_AUTHENTICITY = 40
MIN_UNCERTAIN_IDENTITY = 0.60

AUTO_ACCEPT = "AUTO_ACCEPT"
REVIEW = "REVIEW"
REJECT = "REJECT"

# Job states passed to decide().
STATE_OPEN = "open"
STATE_CLOSED = "closed"
STATE_EXCLUDED = "excluded"
STATE_INVALID_URL = "invalid_url"

# Confidence scoring weights (verify._score_base). Centralized here so the
# Phase-4 calibration pass tunes them from labeled data in one place.
SCORE_COMPLETENESS_WEIGHT = 48
SCORE_FRESH_BONUS = 24
SCORE_RECENT_BONUS = 16
SCORE_OLDER_BONUS = 4
SCORE_STALE_PENALTY = 10
SCORE_ATS_BOOST = 10
SCORE_EXPIRED_PENALTY = 20
SCORE_CAP = 80
SCORE_DOMAIN_MATCH_BOOST = 25
SCORE_DOMAIN_MATCH_CAP = 55
SCORE_BLOCKED_CAP = 40

# Sources with source_authority >= this value get the employer-ATS trust boost
# in confidence scoring (aggregators are 2 or below on the authority scale).
SCORE_ATS_MIN_AUTHORITY = 3
