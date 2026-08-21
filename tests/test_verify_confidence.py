from __future__ import annotations

from unittest import mock

from jobharness import verify
from jobharness.models import CLOSED, VALID_AUTHENTIC, Job


def make_job(url="https://acme.com/careers/1", company="Acme"):
    j = Job(title="Backend Engineer", company=company, location="Remote")
    j.apply_url_direct = url
    j.date_posted = "2023-11-14"
    j.experience_needed = "5+ years"
    return j


class _Resp:
    def __init__(self, status=200, text="Apply now. We are hiring.", url="https://acme.com/careers/1"):
        self.status_code = status
        self._text = text
        self.url = url

    def iter_bytes(self, chunk_size=8192):
        yield self._text.encode("utf-8")


class _Ctx:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *a):
        return False

    def stream(self, method, url, timeout=None):
        return self


def test_verify_confidence_employer_domain_match_boosts_score():
    job = make_job(url="https://acme.com/careers/1", company="Acme")
    with mock.patch("jobharness.verify.get_shared_client", return_value=_Ctx(_Resp())):
        verify.verify(job)
    assert job.authentic_status == VALID_AUTHENTIC
    assert job.employer_domain == "acme.com"
    # domain matches company hint -> boosted beyond the base cap
    assert job.confidence_score >= 55


def test_verify_confidence_aggregator_domain_caps_lower():
    job = make_job(url="https://remoteok.com/l/123", company="Acme")
    with mock.patch("jobharness.verify.get_shared_client", return_value=_Ctx(_Resp(url="https://remoteok.com/l/123"))):
        verify.verify(job)
    assert job.employer_domain == "remoteok.com"
    # company "acme" not in "remoteok.com" -> capped low
    assert job.confidence_score <= 55


def test_verify_validthrough_past_marks_closed():
    job = make_job()
    job.valid_through = "2000-01-01"  # in the past
    verify.verify(job, check_reachable=True)
    assert job.authentic_status == CLOSED


def test_verify_validthrough_future_stays_authentic():
    job = make_job()
    job.valid_through = "2099-12-31"
    with mock.patch("jobharness.verify.get_shared_client", return_value=_Ctx(_Resp())):
        verify.verify(job)
    assert job.authentic_status == VALID_AUTHENTIC


def test_verify_empty_url_closed_and_no_network():
    job = make_job(url="")
    # even with check_reachable True, empty url short-circuits to CLOSED
    with mock.patch("jobharness.verify.get_shared_client") as mc:
        verify.verify(job)
        mc.assert_not_called()
    assert job.authentic_status == CLOSED


def test_verify_closed_marker_excludes():
    job = make_job()
    with mock.patch("jobharness.verify.get_shared_client", return_value=_Ctx(_Resp(text="This position is no longer accepting applications."))):
        verify.verify(job)
    assert job.authentic_status == CLOSED


def test_score_base_fixed_fixture_values():
    """Weight constants must reproduce the historical score for a fixture job."""
    job = make_job()
    job.source_name = "greenhouse"
    job.date_posted = "2026-08-22"  # future → fresh
    job.valid_through = ""
    score = verify._score_base(job)
    assert score == 80  # completeness 48 + fresh 24 + ATS boost 10 = 82, capped at 80


def test_score_base_aggregator_no_ats_boost():
    job = make_job()
    job.source_name = "remoteok"
    job.date_posted = "2026-08-22"  # future → fresh
    score = verify._score_base(job)
    assert score == 72  # 48 + 24, no ATS boost


def test_score_base_ats_boost_follows_authority_map():
    """Boost must be derived from SOURCE_AUTHORITY, not a hardcoded list."""
    job = make_job()
    job.source_name = "somebrandnewname"
    job.date_posted = "2026-08-01"  # older: base = 48 + 4 = 52
    with mock.patch("jobharness.verify.source_authority", return_value=5):
        assert verify._score_base(job) == 62
    with mock.patch("jobharness.verify.source_authority", return_value=2):
        assert verify._score_base(job) == 52
