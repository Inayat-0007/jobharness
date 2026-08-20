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
