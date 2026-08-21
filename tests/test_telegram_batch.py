from __future__ import annotations

from unittest import mock

import pytest

from jobharness.models import VALID_AUTHENTIC, Job
from jobharness.notify import telegram


@pytest.fixture(autouse=True)
def _reset_telegram_state():
    telegram._client = None
    telegram._file_client = None
    telegram.push_stats.update(sent=0, failed=0)
    yield


class FakeResp:
    def __init__(self, status=200, text='{"ok":true}'):
        self.status_code = status
        self._text = text
        self.headers = {}

    @property
    def text(self):
        return self._text


class RecordingCtx:
    def __init__(self, resp):
        self._resp = resp
        self.posts = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs.get("json")))
        return self._resp


def _make_job(i: int, desc_len: int = 0) -> Job:
    j = Job(title=f"Title {i}", company="Acme", location="NY")
    j.role = f"Role {i}"
    j.date_posted = "2026-01-01"
    j.experience_needed = "5+ years"
    j.salary_if_present = "$100k"
    j.freshness = "fresh"
    j.source_name = "test"
    j.apply_url_direct = f"https://example.com/job/{i}"
    j.confidence_score = 90
    j.authentic_status = VALID_AUTHENTIC
    j.genuinely_new = True
    j.decision = 'AUTO_ACCEPT'
    if desc_len:
        j.reason = ["x" * desc_len]
    return j


def _secrets(monkeypatch):
    monkeypatch.setattr(
        telegram.secrets, "get", lambda k, default="": {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"}.get(k, default)
    )


def test_single_job_uses_send_message(monkeypatch):
    _secrets(monkeypatch)
    ctx = RecordingCtx(FakeResp(200))
    with mock.patch("httpx.Client", return_value=ctx):
        n = telegram.notify_new([_make_job(1)])
    assert n == 1
    urls = [u for u, _ in ctx.posts]
    assert urls == ["https://api.telegram.org/bottok/sendMessage"]
    assert telegram.push_stats == {"sent": 1, "failed": 0}


def test_eleven_jobs_sent_sequentially(monkeypatch):
    _secrets(monkeypatch)
    monkeypatch.setattr(telegram.time, "sleep", lambda *a: None)
    ctx = RecordingCtx(FakeResp(200))
    jobs = [_make_job(i) for i in range(11)]
    with mock.patch("httpx.Client", return_value=ctx):
        n = telegram.notify_new(jobs)
    assert n == 11
    assert len(ctx.posts) == 11
    for i, (url, payload) in enumerate(ctx.posts):
        assert url.endswith("/sendMessage")
        assert f"Role {i}" in payload["text"]
        assert f"https://example.com/job/{i}" in payload["text"]
    assert telegram.push_stats == {"sent": 11, "failed": 0}


def test_batch_sleeps_half_second_between_sends(monkeypatch):
    _secrets(monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr(telegram.time, "sleep", sleeps.append)
    ctx = RecordingCtx(FakeResp(200))
    with mock.patch("httpx.Client", return_value=ctx):
        n = telegram.notify_new([_make_job(i) for i in range(3)])
    assert n == 3
    assert sleeps == [0.5, 0.5]


def test_long_cards_sent_individually(monkeypatch):
    _secrets(monkeypatch)
    monkeypatch.setattr(telegram.time, "sleep", lambda *a: None)
    ctx = RecordingCtx(FakeResp(200))
    jobs = [_make_job(1, desc_len=3000), _make_job(2)]
    with mock.patch("httpx.Client", return_value=ctx):
        n = telegram.notify_new(jobs)
    assert n == 2
    urls = [u for u, _ in ctx.posts]
    assert all(u.endswith("/sendMessage") for u in urls)
    assert "Role 1" in ctx.posts[0][1]["text"]
    assert "Role 2" in ctx.posts[1][1]["text"]


def test_truncate_card_helper_keeps_short_text_unchanged():
    assert telegram._truncate_card("short") == "short"


def test_truncate_card_helper_drops_link_when_long():
    link = '<a href="https://example.com/apply?q=1">Apply directly</a>'
    head = "Line one\nLine two\n" + ("z" * 4000)
    out = telegram._truncate_card(head + link)
    assert len(out) <= 1024
    assert out.endswith("...")
    assert "<a href=" not in out


def test_send_retries_once_on_429_then_succeeds(monkeypatch):
    _secrets(monkeypatch)
    monkeypatch.setattr(telegram.time, "sleep", lambda *a: None)

    class SeqCtx:
        def __init__(self):
            self.posts = []
            self._i = 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs.get("json")))
            r = FakeResp(429) if self._i == 0 else FakeResp(200)
            self._i += 1
            return r

    ctx = SeqCtx()
    with mock.patch("httpx.Client", return_value=ctx):
        n = telegram.notify_new([_make_job(i) for i in range(3)])
    assert n == 3
    assert len(ctx.posts) == 4
    assert telegram.push_stats == {"sent": 3, "failed": 0}


def test_send_failure_counts_failed(monkeypatch):
    _secrets(monkeypatch)
    monkeypatch.setattr(telegram.time, "sleep", lambda *a: None)
    ctx = RecordingCtx(FakeResp(500))
    with mock.patch("httpx.Client", return_value=ctx):
        n = telegram.notify_new([_make_job(1), _make_job(2)])
    assert n == 0
    assert telegram.push_stats == {"sent": 0, "failed": 2}
