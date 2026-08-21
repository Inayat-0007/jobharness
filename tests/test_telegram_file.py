from __future__ import annotations

from unittest import mock

import pytest

from jobharness.notify import telegram


@pytest.fixture(autouse=True)
def _reset_telegram_state():
    telegram._client = None
    telegram._file_client = None
    telegram.push_stats.update(sent=0, failed=0)
    yield


class FakeResp:
    def __init__(self, status=200):
        self.status_code = status
        self.headers = {}


class FakeCtx:
    def __init__(self, resp):
        self._resp = resp
        self.posted = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **k):
        self.posted = k
        return self._resp


def test_send_file_posts_document(monkeypatch, tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("a,b\n1,2", encoding="utf-8")
    ctx = FakeCtx(FakeResp(200))
    monkeypatch.setattr(telegram.secrets, "get", lambda k, default="": {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"}.get(k, default))
    with mock.patch("httpx.Client", return_value=ctx):
        ok = telegram.send_file(str(f), caption="Job harness run 1: 3 new")
    assert ok is True
    assert ctx.posted is not None
    assert ctx.posted["data"]["chat_id"] == "chat"
    assert ctx.posted["data"]["caption"] == "Job harness run 1: 3 new"
    assert "document" in ctx.posted["files"]


def test_send_file_caption_truncated_to_1024(monkeypatch, tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("x", encoding="utf-8")
    ctx = FakeCtx(FakeResp(200))
    monkeypatch.setattr(telegram.secrets, "get", lambda k, default="": {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"}.get(k, default))
    with mock.patch("httpx.Client", return_value=ctx):
        telegram.send_file(str(f), caption="x" * 5000)
    assert len(ctx.posted["data"]["caption"]) == 1024


def test_send_file_non_200_returns_false(monkeypatch, tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("x", encoding="utf-8")
    ctx = FakeCtx(FakeResp(500))
    monkeypatch.setattr(telegram.secrets, "get", lambda k, default="": {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"}.get(k, default))
    with mock.patch("httpx.Client", return_value=ctx):
        assert telegram.send_file(str(f)) is False


def test_send_file_unconfigured_returns_false(monkeypatch):
    monkeypatch.setattr(telegram.secrets, "get", lambda k, default="": "")
    assert telegram.send_file("whatever.csv") is False


def test_send_file_missing_file_returns_false(monkeypatch):
    monkeypatch.setattr(telegram.secrets, "get", lambda k, default="": {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"}.get(k, default))
    with mock.patch("httpx.Client"):
        assert telegram.send_file("/nonexistent/file.csv") is False
