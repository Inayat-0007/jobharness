from __future__ import annotations

from jobharness.sources.rss.remotive import _company_from_title


class _Entry:
    def __init__(self, title, author="", link="https://remotive.com/x", summary="", published=""):
        self._d = {"title": title, "author": author, "link": link, "summary": summary, "published": published}

    def get(self, k, default=""):
        return self._d.get(k, default)


class _Parsed:
    def __init__(self, entries):
        self.entries = entries


class _Resp:
    def __init__(self, parsed):
        self.status_code = 200
        self.content = b""
        self._parsed = parsed

    @property
    def text(self):
        return ""


class _Ctx:
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def get(self,*a,**k): return _Resp(None)


def test_company_from_title_dash():
    assert _company_from_title("Acme - Backend Engineer") == "Acme"


def test_company_from_title_endash():
    assert _company_from_title("Acme \u2013 Backend Engineer") == "Acme"


def test_company_from_title_no_dash():
    assert _company_from_title("Backend Engineer") == ""


def test_remotive_uses_author_when_present(monkeypatch):
    import jobharness.sources.rss.remotive as rm

    entries = [_Entry(title="Backend Engineer", author="Acme Corp")]
    monkeypatch.setattr(rm.feedparser, "parse", lambda content: _Parsed(entries))
    from jobharness.profile import Profile

    out = rm.RemotiveAdapter().fetch(Profile(roles=["Backend Engineer"]))
    assert out and out[0].company == "Acme Corp"


def test_remotive_falls_back_to_title_company_no_author(monkeypatch):
    import jobharness.sources.rss.remotive as rm

    entries = [_Entry(title="Startup Inc - Backend Engineer", author="")]
    monkeypatch.setattr(rm.feedparser, "parse", lambda content: _Parsed(entries))
    from jobharness.profile import Profile

    out = rm.RemotiveAdapter().fetch(Profile(roles=["Backend Engineer"]))
    assert out and out[0].company == "Startup Inc"
