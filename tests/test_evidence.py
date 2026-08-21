from __future__ import annotations

from jobharness.models import Job, CLOSED, VALID_AUTHENTIC
from jobharness.evidence.positive import positive_signals
from jobharness.evidence.negative import negative_signals
from jobharness.evidence.reason import compose_reasons, reason_text
from jobharness.evidence.source import SOURCE_AUTHORITY, source_authority, SourceStatus
from jobharness.scoring.authenticity import authenticity_score


def rich_job():
    j = Job(
        title="Backend Engineer", company="Acme", location="Remote",
        description="python api", experience_needed="5+ years",
    )
    j.source_name = "greenhouse"
    j.source_authority = SOURCE_AUTHORITY["greenhouse"]
    j.apply_url_direct = "https://careers.acme.com/jobs/4123456"
    j.employer_domain = "careers.acme.com"
    j.posting_id = "4123456"
    j.date_posted = "2023-11-14"
    j.freshness = "fresh"
    j.authentic_status = VALID_AUTHENTIC
    j.seen_sources = ["greenhouse"]
    return j


def test_positive_signals():
    j = rich_job()
    sig = positive_signals(j)
    assert "official_ats_source" in sig
    assert "official_domain" in sig
    assert "valid_posting_id" in sig
    assert "active_application" in sig
    assert "current_posting" in sig


def test_positive_signals_aggregator_weak():
    j = rich_job()
    j.source_name = "remoteok"
    j.source_authority = SOURCE_AUTHORITY["remoteok"]
    sig = positive_signals(j)
    assert "official_ats_source" not in sig


def test_negative_signals_closed():
    j = rich_job()
    j.authentic_status = CLOSED
    j.valid_through = "2000-01-01"
    sig = negative_signals(j)
    assert "closed_state" in sig
    assert "expired_valid_through" in sig


def test_negative_signals_from_verify_context():
    j = rich_job()
    ctx = {"status_code": 404, "redirect_to": "https://acme.com/careers"}
    sig = negative_signals(j, ctx)
    assert "http_gone" in sig


def test_negative_signals_domain_mismatch():
    j = rich_job()
    j.employer_domain = "remoteok.com"
    sig = negative_signals(j)
    assert "employer_domain_mismatch" in sig


def test_negative_signals_broken_application():
    j = rich_job()
    j.apply_url_direct = ""
    sig = negative_signals(j)
    assert "broken_application" in sig


def test_reason_composition():
    reasons = compose_reasons(["official_ats_source", "valid_posting_id"], ["closed_state"])
    assert reasons[0] == "official ATS/API source"
    assert reasons[-1] == "negative: job marked closed"
    assert reason_text("unknown_signal") == "unknown signal"


def test_source_authority_map():
    assert source_authority("greenhouse") == 5
    assert source_authority("career_page_generic") == 4
    assert source_authority("google_jobs") == 3
    assert source_authority("remoteok") == 2
    assert source_authority("linkedin") == 0
    # Intent: unknown/unmapped sources rank above KNOWN aggregators (0),
    # because an unmapped source is usually a direct employer page.
    assert source_authority("mystery_source") == 1
    assert source_authority("") == 1
    assert source_authority(None) == 1


def test_authenticity_score_range():
    j = rich_job()
    j.valid_through = "2099-12-31"
    high = authenticity_score(j)
    assert high >= 60

    j2 = rich_job()
    j2.authentic_status = CLOSED
    j2.valid_through = "2000-01-01"
    low = authenticity_score(j2)
    assert low < high
    assert low < 55
    assert 0.0 <= low <= 100.0


def test_source_status_enum_values():
    assert SourceStatus.EMPTY.value == "empty"
    assert SourceStatus.RATE_LIMITED.value == "rate_limited"
    assert SourceStatus.AUTH_REQUIRED.value == "auth_required"
    assert SourceStatus.SOURCE_DOWN.value == "source_down"
    assert SourceStatus.PARSE_FAILURE.value == "parse_failure"
    assert SourceStatus.NO_MATCH.value == "no_match"
