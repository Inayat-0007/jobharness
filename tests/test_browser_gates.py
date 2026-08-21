from __future__ import annotations

from jobharness import browser as browser_mod
from jobharness.browser import wait_for_captcha, wait_for_login


class _FakePage:
    """Minimal page stub: `wall()` is called on each poll to flip state."""

    def __init__(self, wall):
        self._wall = wall
        self.calls = 0
        self.goto_count = 0

    def query_selector(self, sel):
        return None

    def goto(self, url, **kw):
        self.goto_count += 1

    def content(self):
        self.calls += 1
        return "captcha here" if self._wall() else "jobs list"


def _no_sleep(monkeypatch):
    monkeypatch.setattr(browser_mod.time, "sleep", lambda s: None)


def test_wait_for_login_returns_after_wall_clears(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def wall(page):
        calls["n"] += 1
        return calls["n"] < 3

    page = _FakePage(wall)
    assert wait_for_login(page, "t", "https://x", wall, timeout=30) is True
    assert page.goto_count == 1  # re-navigated after login detected


def test_wait_for_login_times_out(monkeypatch):
    _no_sleep(monkeypatch)
    page = _FakePage(lambda p: True)
    assert wait_for_login(page, "t", "https://x", lambda p: True, timeout=9) is False
    assert page.goto_count == 0


def test_wait_for_captcha_returns_when_solved(monkeypatch):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def wall():
        calls["n"] += 1
        return calls["n"] < 3

    page = _FakePage(wall)
    assert wait_for_captcha(page, "t", timeout=30) is True


def test_wait_for_captcha_times_out(monkeypatch):
    _no_sleep(monkeypatch)
    page = _FakePage(lambda: True)
    assert wait_for_captcha(page, "t", timeout=9) is False


def test_wait_for_captcha_check_error_returns_false(monkeypatch):
    """A detect_block that raises must be treated as NOT solved (fail-closed)."""
    _no_sleep(monkeypatch)

    def boom(page):
        raise RuntimeError("page closed")

    monkeypatch.setattr(browser_mod, "detect_block", boom)
    page = _FakePage(lambda: True)
    assert wait_for_captcha(page, "t", timeout=9) is False
