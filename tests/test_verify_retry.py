from __future__ import annotations

from unittest import mock

import httpx
import pytest

from jobharness import verify
from jobharness.models import CLOSED, VALID_AUTHENTIC, Job
from jobharness.profile import Profile
from jobharness.sources.api.remoteok import RemoteOKAdapter
from jobharness.sources.exceptions import ParseFailureError


def make_job(url="https://acme.com/careers/1"):
    j = Job(title="Backend Engineer", company="Acme", location="Remote")
    j.apply_url_direct = url
    j.date_posted = "2026-08-22"  # future -> fresh
    j.experience_needed = "5+ years"
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


class _Flaky:
    """Serves a fixed sequence of stream() outcomes (responses or exceptions)."""

    def __init__(self, items):
        self._items = list(items)
        self.stream_calls = 0

    def stream(self, *a, **k):
        item = self._items[min(self.stream_calls, len(self._items) - 1)]
        self.stream_calls += 1
        if isinstance(item, Exception):
            raise item
        return item


def test_transient_httpx_error_after_retries_marks_degraded():
    job = make_job()
    flaky = _Flaky([httpx.ConnectError("connect refused")])
    with mock.patch("jobharness.verify.get_shared_client", return_value=flaky):
        with mock.patch("jobharness.verify.time.sleep") as slp:
            verify.verify(job)
    assert job.authentic_status == "DEGRADED"
    assert job.authentic_status != CLOSED
    assert flaky.stream_calls == 3  # initial + 2 retries
    assert slp.call_args_list == [mock.call(0.5), mock.call(2.0)]  # exponential backoff
    assert job.confidence_score == 57  # base 72 - 15 degraded penalty
    assert "verification_unreachable" in job.negative_evidence
    assert "verification_unreachable" in job.reason


def test_oserror_after_retries_marks_degraded_not_closed():
    job = make_job()
    flaky = _Flaky([OSError("dns failure")])
    with mock.patch("jobharness.verify.get_shared_client", return_value=flaky):
        with mock.patch("jobharness.verify.time.sleep"):
            verify.verify(job)
    assert job.authentic_status == "DEGRADED"
    assert job.decision == ""  # degraded is not a hard REJECT/CLOSED


def test_404_closed_without_retries():
    job = make_job()
    flaky = _Flaky([_Stream(_Resp(status=404, text="Not found"))])
    with mock.patch("jobharness.verify.get_shared_client", return_value=flaky):
        with mock.patch("jobharness.verify.time.sleep") as slp:
            verify.verify(job)
    assert job.authentic_status == CLOSED
    assert job.decision == "REJECT"
    assert flaky.stream_calls == 1
    slp.assert_not_called()


def test_429_retried_then_success_stays_authentic():
    job = make_job()
    flaky = _Flaky([_Stream(_Resp(status=429)), _Stream(_Resp(status=200, text="Apply now."))])
    with mock.patch("jobharness.verify.get_shared_client", return_value=flaky):
        with mock.patch("jobharness.verify.time.sleep") as slp:
            verify.verify(job)
    assert job.authentic_status == VALID_AUTHENTIC
    assert slp.call_args_list == [mock.call(0.5)]
    assert flaky.stream_calls == 2


def test_429_persistent_after_retries_degraded():
    job = make_job()
    flaky = _Flaky([_Stream(_Resp(status=429))])
    with mock.patch("jobharness.verify.get_shared_client", return_value=flaky):
        with mock.patch("jobharness.verify.time.sleep") as slp:
            verify.verify(job)
    assert job.authentic_status == "DEGRADED"
    assert slp.call_count == 2
    assert flaky.stream_calls == 3


def test_999_retried_then_success_stays_authentic():
    job = make_job()
    flaky = _Flaky([_Stream(_Resp(status=999)), _Stream(_Resp(status=200, text="Apply now."))])
    with mock.patch("jobharness.verify.get_shared_client", return_value=flaky):
        with mock.patch("jobharness.verify.time.sleep") as slp:
            verify.verify(job)
    assert job.authentic_status == VALID_AUTHENTIC
    assert slp.call_args_list == [mock.call(0.5)]
    assert flaky.stream_calls == 2


def test_999_persistent_after_retries_degraded_not_closed():
    job = make_job()
    flaky = _Flaky([_Stream(_Resp(status=999))])
    with mock.patch("jobharness.verify.get_shared_client", return_value=flaky):
        with mock.patch("jobharness.verify.time.sleep") as slp:
            verify.verify(job)
    assert job.authentic_status == "DEGRADED"
    assert job.authentic_status != CLOSED
    assert slp.call_count == 2
    assert flaky.stream_calls == 3


def test_5xx_persistent_after_retries_degraded():
    job = make_job()
    flaky = _Flaky([_Stream(_Resp(status=503))])
    with mock.patch("jobharness.verify.get_shared_client", return_value=flaky):
        with mock.patch("jobharness.verify.time.sleep"):
            verify.verify(job)
    assert job.authentic_status == "DEGRADED"
    assert job.authentic_status != CLOSED


class _JsonResp:
    def __init__(self, data):
        self._data = data
        self.status_code = 200
        self.text = str(data)

    def json(self):
        return self._data


class _JsonCtx:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return _JsonResp(self._data)


def _fetch_remoteok(payload):
    adapter = RemoteOKAdapter()
    with mock.patch("jobharness.sources.api.remoteok.make_client", return_value=_JsonCtx(payload)):
        with mock.patch("jobharness.sources.api.remoteok.blocked_response", return_value=False):
            with mock.patch("jobharness.sources.api.remoteok.random_delay"):
                return adapter.fetch(Profile(roles=["Backend Engineer"]))


def test_remoteok_dict_wrapper_unwrapped():
    payload = {"data": [
        {"slug": "dev-acme", "position": "Backend Dev", "company": "Acme", "url": "/l/1",
         "description": "Python", "date": 1700000000000}
    ]}
    raws = _fetch_remoteok(payload)
    assert len(raws) == 1
    assert raws[0].title == "Backend Dev"
    assert raws[0].company == "Acme"
    assert raws[0].apply_url == "https://remoteok.com/l/1"


def test_remoteok_malformed_dict_raises_parse_failure():
    with pytest.raises(ParseFailureError):
        _fetch_remoteok({"error": "boom"})


def test_remoteok_non_list_payload_raises_parse_failure():
    with pytest.raises(ParseFailureError):
        _fetch_remoteok("oops")


def test_remoteok_list_of_non_dicts_raises_parse_failure():
    with pytest.raises(ParseFailureError):
        _fetch_remoteok([1, 2, 3])
