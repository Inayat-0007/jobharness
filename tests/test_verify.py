from __future__ import annotations

from unittest import mock

from jobharness import verify
from jobharness.models import CLOSED, VALID_AUTHENTIC, Job


def make_job(url="https://acme.com/careers/1"):
    j = Job(title="Backend Engineer", company="Acme", location="Remote")
    j.apply_url_direct = url
    return j


class _Resp:
    def __init__(self, status=200, text="Apply now. We are hiring.", url="https://acme.com/careers/1"):
        self.status_code = status
        self._text = text
        self.url = url

    def iter_bytes(self, chunk_size=8192):
        yield self._text.encode("utf-8")


class _Stream:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *a):
        return False

    def stream(self, method, url, timeout=None):
        return self


def test_transient_status_999_is_transient():
    assert verify._transient_status(999)


def test_verify_marks_unreachable_as_degraded():
    job = make_job("https://example.com/gone")

    class BoomClient:
        def stream(self, *a, **k):
            raise OSError("boom")

    with mock.patch("jobharness.verify.get_shared_client", return_value=BoomClient()):
        with mock.patch("jobharness.verify.time.sleep"):
            verify.verify(job)
    assert job.authentic_status == "DEGRADED"
    assert job.authentic_status != CLOSED


def test_verify_marks_404_closed():
    job = make_job()
    with mock.patch("jobharness.verify.get_shared_client", return_value=_Stream(_Resp(status=404, text="Not found"))):
        verify.verify(job)
    assert job.authentic_status == CLOSED


def test_verify_detects_closed_marker():
    job = make_job()
    resp = _Resp(status=200, text="This position is no longer accepting applications.")
    with mock.patch("jobharness.verify.get_shared_client", return_value=_Stream(resp)):
        verify.verify(job)
    assert job.authentic_status == CLOSED


def test_verify_healthy_job_stays_authentic():
    job = make_job()
    with mock.patch("jobharness.verify.get_shared_client", return_value=_Stream(_Resp())):
        verify.verify(job)
    assert job.authentic_status == VALID_AUTHENTIC


def test_verify_empty_url_closed():
    job = make_job("")
    verify.verify(job, check_reachable=True)
    assert job.authentic_status == CLOSED
