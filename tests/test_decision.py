from __future__ import annotations

from jobharness.scoring.decision import decide
from jobharness.scoring.thresholds import (
    AUTO_ACCEPT,
    AUTO_ACCEPT_AUTHENTICITY,
    AUTO_ACCEPT_IDENTITY,
    AUTO_ACCEPT_MATCH,
    MEDIUM_AUTHENTICITY,
    REJECT,
    REVIEW,
    REVIEW_MATCH,
    STATE_CLOSED,
    STATE_EXCLUDED,
    STATE_INVALID_URL,
    STATE_OPEN,
)


def test_hard_states_always_reject():
    assert decide(0.99, 95, 0.9, STATE_CLOSED)[0] == REJECT
    assert decide(0.99, 95, 0.9, STATE_EXCLUDED)[0] == REJECT
    assert decide(0.99, 95, 0.9, STATE_INVALID_URL)[0] == REJECT


def test_hard_state_reasons():
    d, reasons = decide(1.0, 95, 0.9, STATE_CLOSED)
    assert d == REJECT
    assert reasons == ["job closed"]


def test_auto_accept_boundaries():
    assert decide(AUTO_ACCEPT_IDENTITY, AUTO_ACCEPT_AUTHENTICITY, AUTO_ACCEPT_MATCH, STATE_OPEN)[0] == AUTO_ACCEPT
    assert decide(1.0, 95, 0.9, STATE_OPEN)[0] == AUTO_ACCEPT


def test_auto_accept_no_candidates():
    d, reasons = decide(0.0, 80, 0.7, STATE_OPEN)
    assert d == AUTO_ACCEPT
    assert "no known duplicates" in reasons


def test_just_below_auto_accept_is_review():
    assert decide(0.94, 95, 0.9, STATE_OPEN)[0] == REVIEW
    assert decide(1.0, AUTO_ACCEPT_AUTHENTICITY - 1, 0.9, STATE_OPEN)[0] == REVIEW
    assert decide(1.0, 95, AUTO_ACCEPT_MATCH - 0.01, STATE_OPEN)[0] == REVIEW


def test_review_medium_relevance():
    d, reasons = decide(1.0, 95, REVIEW_MATCH, STATE_OPEN)
    assert d == REVIEW
    assert "relevance medium" in reasons


def test_review_uncertain_identity():
    d, reasons = decide(0.8, 95, 0.9, STATE_OPEN)
    assert d == REVIEW
    assert "identity uncertain" in reasons


def test_review_medium_authenticity():
    d, reasons = decide(1.0, MEDIUM_AUTHENTICITY + 1, 0.9, STATE_OPEN)
    assert d == REVIEW
    assert "authenticity medium" in reasons


def test_low_relevance_rejects_even_high_scores():
    assert decide(1.0, 95, REVIEW_MATCH - 0.01, STATE_OPEN)[0] == REJECT


def test_reject_when_below_all_thresholds():
    assert decide(0.0, 20, 0.1, STATE_OPEN)[0] == REJECT
    assert decide(0.5, 30, REVIEW_MATCH - 0.01, STATE_OPEN)[0] == REJECT
