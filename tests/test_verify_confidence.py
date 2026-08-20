from __future__ import annotations

from unittest import mock

from jobharness.models import Job, CLOSED, VALID_AUTHENTIC
from jobharness import verify


def make_job(url="https://acme.com/careers/1", company="Acme"):
    j = Job(title="Backend Engineer", company=company, location="Remote")
    j.apply_url_direct = url
    j.date_posted = "2023-11-14"
    j.experience_needed = "5+ years"
    return j


class _Resp:
    def __init__(self, status=200, text="Apply now. We are hiring.", url="https://acme.com/careers/1"):
        self.status_code = status
        self.text = text
        self.url = url


class _Ctx:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return self._resp


def test_verify_confidence_employer_domain_match_boosts_score():
    job = make_job(url="https://acme.com/careers/1", company="Acme")
    with mock.patch("jobharness.verify.make_client", return_value=_Ctx(_Resp())):
        verify.verify(job)
    assert job.authentic_status == VALID_AUTHENTIC
    assert job.employer_domain == "acme.com"
    # domain matches company hint -> boosted beyond the base cap
    assert job.confidence_score >= 55


def test_verify_confidence_aggregator_domain_caps_lower():
    job = make_job(url="https://remoteok.com/l/123", company="Acme")
    with mock.patch("jobharness.verify.make_client", return_value=_Ctx(_Resp(url="https://remoteok.com/l/123"))):
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
    with mock.patch("jobharness.verify.make_client", return_value=_Ctx(_Resp())):
        verify.verify(job)
    assert job.authentic_status == VALID_AUTHENTIC


def test_verify_empty_url_closed_and_no_network():
    job = make_job(url="")
    # even with check_reachable True, empty url short-circuits to CLOSED
    with mock.patch("jobharness.verify.make_client") as mc:
        verify.verify(job)
        mc.assert_not_called()
    assert job.authentic_status == CLOSED


def test_verify_closed_marker_excludes():
    job = make_job()
    with mock.patch("jobharness.verify.make_client", return_value=_Ctx(_Resp(text="This position is no longer accepting applications."))):
        verify.verify(job)
    assert job.authentic_status == CLOSED
