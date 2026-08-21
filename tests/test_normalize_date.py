from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jobharness.extractor import normalize_date
from jobharness.models import _parse_date, freshness_label


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


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


def test_normalize_date_relative():
    assert normalize_date("today") == _days_ago(0)
    assert normalize_date("yesterday") == _days_ago(1)
    assert normalize_date("2 days ago") == _days_ago(2)
    assert normalize_date("2 day ago") == _days_ago(2)
    assert normalize_date("2d ago") == _days_ago(2)
    assert normalize_date("posted 1 week ago") == _days_ago(7)
    assert normalize_date("Posted 3 days ago") == _days_ago(3)
    assert normalize_date("1 week ago") == _days_ago(7)
    assert normalize_date("2 months ago") == _days_ago(60)
    assert normalize_date("POSTED TODAY") == _days_ago(0)


def test_parse_date_relative_hours_is_midnight():
    d = _parse_date("5 hours ago")
    assert d is not None
    assert (d.hour, d.minute, d.second) == (0, 0, 0)
    assert d.date().isoformat() in (_days_ago(0), _days_ago(1))
    assert d.tzinfo is not None


def test_parse_date_dmy_vs_mdy():
    # DMY is the default (current behavior): 04/05/2024 -> 4 May.
    assert _parse_date("04/05/2024").strftime("%Y-%m-%d") == "2024-05-04"
    assert _parse_date("04/05/2024", date_format="DMY").strftime("%Y-%m-%d") == "2024-05-04"
    assert _parse_date("04/05/2024", date_format="MDY").strftime("%Y-%m-%d") == "2024-04-05"


def test_parse_date_iso_stays_first():
    assert _parse_date("2024-05-04T10:00:00Z", date_format="MDY").strftime("%Y-%m-%d") == "2024-05-04"


def test_normalize_date_mdy_param():
    assert normalize_date("04/05/2024", date_format="MDY") == "2024-04-05"


def test_remoteok_epoch_freshness_is_not_missing():
    # RemoteOK returns epoch seconds; freshness should resolve to a real label.
    label = freshness_label(str(1700000000))
    assert label in ("fresh", "recent", "older", "stale")
    assert label != "MISSING"


def test_parse_date_accepts_int():
    assert _parse_date(1700000000) is not None
    dt = _parse_date(1700000000)
    assert dt.year == 2023 and dt.month == 11


def test_parse_date_huge_relative_days_does_not_crash():
    clamped = (datetime.now(timezone.utc).date() - timedelta(days=365_000))
    d = _parse_date("99999999999999999999 days ago")
    assert d is None or d.date() >= clamped
    assert _parse_date("99999999999999999999 weeks ago") is None
    assert _parse_date("99999999999999999999 months ago") is None


def test_parse_date_huge_relative_hours_does_not_crash():
    clamped = (datetime.now(timezone.utc).date() - timedelta(days=365_000))
    d = _parse_date("99999999999999999999 hours ago")
    assert d is None or d.date() >= clamped
