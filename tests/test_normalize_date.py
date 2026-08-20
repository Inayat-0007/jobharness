from __future__ import annotations

from jobharness.extractor import normalize_date
from jobharness.models import freshness_label, _parse_date


def test_normalize_date_iso_with_z():
    assert normalize_date("2023-11-14T10:00:00Z") == "2023-11-14"


def test_normalize_date_iso_with_offset():
    assert normalize_date("2023-11-14T10:00:00+00:00") == "2023-11-14"


def test_normalize_date_rfc2822():
    assert normalize_date("Wed, 14 Nov 2023 10:00:00 GMT") == "2023-11-14"


def test_normalize_date_plain_date():
    assert normalize_date("2023-11-14") == "2023-11-14"


def test_normalize_date_epoch_seconds():
    # 1700000000 ~= 2023-11-14 22:13:20 UTC
    assert normalize_date(1700000000) == "2023-11-14"
    assert normalize_date("1700000000") == "2023-11-14"


def test_normalize_date_epoch_ms():
    # 1700000000000 ms == 1700000000 s
    assert normalize_date(1700000000000) == "2023-11-14"
    assert normalize_date("1700000000000") == "2023-11-14"


def test_normalize_date_garbage_returns_empty():
    assert normalize_date("not a date") == ""
    assert normalize_date("") == ""
    assert normalize_date(None) == ""
    assert normalize_date("MISSING") == ""


def test_remoteok_epoch_freshness_is_not_missing():
    # RemoteOK returns epoch seconds; freshness should resolve to a real label.
    label = freshness_label(str(1700000000))
    assert label in ("fresh", "recent", "older", "stale")
    assert label != "MISSING"


def test_parse_date_accepts_int():
    assert _parse_date(1700000000) is not None
    dt = _parse_date(1700000000)
    assert dt.year == 2023 and dt.month == 11
