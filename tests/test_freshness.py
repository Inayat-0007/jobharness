from __future__ import annotations

from jobharness.models import freshness_label, MISSING


def test_freshness_rfc2822():
    assert freshness_label("Wed, 14 Nov 2023 10:00:00 GMT") in ("fresh", "recent", "older", "stale")


def test_freshness_iso_with_z():
    # near-today date -> one of the defined labels, not MISSING
    label = freshness_label("2026-08-20T10:00:00Z")
    assert label in ("fresh", "recent", "older", "stale")
    assert label != MISSING


def test_freshness_iso_with_offset():
    assert freshness_label("2023-11-14T10:00:00+00:00") in ("fresh", "recent", "older", "stale")


def test_freshness_plain_date():
    assert freshness_label("2023-11-14") in ("fresh", "recent", "older", "stale")


def test_freshness_missing_returns_missing():
    assert freshness_label("") == MISSING
    assert freshness_label("MISSING") == MISSING


def test_freshness_garbage_falls_back_to_tokens():
    # text with "day" token but no parseable date
    assert freshness_label("1 day ago") == "fresh"


def test_freshness_future_returns_fresh():
    # a date far in the future
    assert freshness_label("2099-01-01") == "fresh"
