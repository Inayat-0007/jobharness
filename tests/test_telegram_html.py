from __future__ import annotations

import html as _html
from unittest import mock

from jobharness.models import VALID_AUTHENTIC, Job
from jobharness.notify import telegram


def _job_with_specials():
    j = Job(title="Backend_Engineer *Lead* (Senior)", company="Acme [Corp]", location="NY")
    j.role = "Backend_Engineer *Lead* (Senior)"
    j.date_posted = "2023-11-14"
    j.experience_needed = "5+ years"
    j.salary_if_present = "$120k-$150k"
    j.freshness = "fresh"
    j.source_name = "remoteok"
    j.apply_url_direct = "https://acme.com/careers?a=1&b=2"
    j.confidence_score = 70
    j.authentic_status = VALID_AUTHENTIC
    j.genuinely_new = True
    return j


class FakeResp:
    def __init__(self, status=200, text='{"ok":true}'):
        self.status_code = status
        self._text = text

    @property
    def text(self):
        return self._text


class FakeCtx:
    captured = None

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **k):
        FakeCtx.captured = k.get("json")
        return self._resp


def test_send_card_uses_html_parse_mode_and_escapes():
    job = _job_with_specials()
    FakeCtx.captured = None
    fake = FakeCtx(FakeResp(200))
    with mock.patch.object(telegram.secrets, "get", side_effect=["tok", "chat"]):
        with mock.patch("httpx.Client", return_value=fake):
            ok = telegram.send_card(job)
    assert ok is True
    payload = FakeCtx.captured
    assert payload is not None
    assert payload["parse_mode"] == "HTML"
    body = payload["text"]
    # The <b>...</b> bold tag is present (intentional HTML formatting)
    assert "<b>" in body and "</b>" in body
    # The apply link is an HTML anchor with an escaped URL (ampersand escaped)
    raw_url_amp = "a=1&b=2"
    escaped_url_amp = _html.escape(raw_url_amp)
    assert raw_url_amp not in body
    assert escaped_url_amp in body
    assert "<a href=" in body and "Apply directly</a>" in body


def test_send_card_surfaces_non_200_not_silent(capsys):
    job = _job_with_specials()
    fake = FakeCtx(FakeResp(400, '{"ok":false,"description":"bad request"}'))
    with mock.patch.object(telegram.secrets, "get", side_effect=["tok", "chat"]):
        with mock.patch("httpx.Client", return_value=fake):
            ok = telegram.send_card(job)
    assert ok is False
    captured = capsys.readouterr().out
    assert "400" in captured


def test_notify_new_skips_low_confidence():
    job = _job_with_specials()
    job.confidence_score = 30
    job.genuinely_new = True
    with mock.patch.object(telegram.secrets, "get", side_effect=["tok", "chat"]):
        with mock.patch("jobharness.notify.telegram.send_card", return_value=True) as sc:
            n = telegram.notify_new([job])
    assert n == 0
    sc.assert_not_called()
