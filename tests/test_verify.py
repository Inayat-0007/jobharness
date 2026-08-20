from __future__ import annotations

from unittest import mock

from jobharness.models import Job, CLOSED, VALID_AUTHENTIC
from jobharness import verify


def make_job(url="https://acme.com/careers/1"):
    j = Job(title="Backend Engineer", company="Acme", location="Remote")
    j.apply_url_direct = url
    return j


def test_verify_marks_unreachable_as_closed():
    job = make_job("https://example.com/gone")
    with mock.patch("jobharness.verify.make_client") as mc:
        mc.side_effect = OSError("boom")
        verify.verify(job)
    assert job.authentic_status == CLOSED


def test_verify_marks_404_closed():
    job = make_job()
    class Resp:
        status_code = 404
        text = "Not found"
        url = "https://example.com/x"
    class Ctx:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def get(self,*a,**k): return Resp()
    with mock.patch("jobharness.verify.make_client", return_value=Ctx()):
        verify.verify(job)
    assert job.authentic_status == CLOSED


def test_verify_detects_closed_marker():
    job = make_job()
    class Resp:
        status_code = 200
        text = "This position is no longer accepting applications."
        url = "https://acme.com/careers/1"
    class Ctx:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def get(self,*a,**k): return Resp()
    with mock.patch("jobharness.verify.make_client", return_value=Ctx()):
        verify.verify(job)
    assert job.authentic_status == CLOSED


def test_verify_healthy_job_stays_authentic():
    job = make_job()
    class Resp:
        status_code = 200
        text = "Apply now. We are hiring a backend engineer."
        url = "https://acme.com/careers/1"
    class Ctx:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def get(self,*a,**k): return Resp()
    with mock.patch("jobharness.verify.make_client", return_value=Ctx()):
        verify.verify(job)
    assert job.authentic_status == VALID_AUTHENTIC


def test_verify_empty_url_closed():
    job = make_job("")
    verify.verify(job, check_reachable=True)
    assert job.authentic_status == CLOSED
