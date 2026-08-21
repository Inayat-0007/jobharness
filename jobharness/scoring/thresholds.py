from __future__ import annotations

# Centralized thresholds (plan 3.2). Never scatter these numbers in
# runner/verify/matcher; Phase 4 benchmark tunes them from labeled data.
#
# Recalibration 2026-08 (AUTO_ACCEPT was structurally unreachable):
# Observed over 4 production runs / 183+ matched jobs — with the OLD
# normalization, max match_score was 0.230 (vs AUTO_ACCEPT_MATCH 0.60) and
# max authenticity 63.3 (vs AUTO_ACCEPT_AUTHENTICITY 70): 100% REVIEW,
# 0 AUTO_ACCEPT. With the saturation-capped normalization in
# scoring/matching.py (a strong match reaches ~0.30-0.55; a saturated title+
# description match can approach ~0.9) and the achievable authenticity
# ceilings (portal/aggregator source_authority<=2 tops out ~43-48 because
# domain_match=0 on portal apply URLs; employer-ATS sources reach ~60-63+),
# the values below are reachable-but-meaningful: AUTO_ACCEPT requires an
# employer-domain/ATS-authentic job (auth >= 55, above the portal ceiling)
# with multi-token role+keyword relevance (match >= 0.30, above the observed
# old-normalization max). PROVISIONAL pending Phase-4 labeled calibration
# (evaluation/benchmark.py); do not treat these as probability-backed.
AUTO_ACCEPT_IDENTITY = 0.95
AUTO_ACCEPT_AUTHENTICITY = 55
AUTO_ACCEPT_MATCH = 0.30
REVIEW_MATCH = 0.20
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

# Fields a Job must have to be considered complete. Single source of truth for
# both Job.mark_missing() and algo.authenticity_features() (completeness), so
# the two can never drift apart.
REQUIRED_JOB_FIELDS = (
    "title",
    "company",
    "apply_url_direct",
    "date_posted",
    "location",
    "experience_needed",
)
