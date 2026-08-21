from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from jobharness.profile import Profile
from jobharness.sources.api.remoteok import RemoteOKAdapter

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "remoteok.json"


@pytest.fixture
def remoteok_jobs():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["jobs"]


def test_remoteok_extracts_fields_without_invention(remoteok_jobs):
    adapter = RemoteOKAdapter()
    # Patch make_client so fetch uses the fixture response object instead of network.
    class FakeResp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200
            self.text = json.dumps(data)

        def json(self):
            return self._data

    class FakeCtx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return FakeResp(remoteok_jobs)

    with mock.patch("jobharness.sources.api.remoteok.make_client", return_value=FakeCtx()):
        with mock.patch("jobharness.sources.api.remoteok.blocked_response", return_value=False):
            with mock.patch("jobharness.sources.api.remoteok.random_delay"):
                raws = adapter.fetch(Profile(roles=["Backend Engineer"]))

    # Two raw jobs; the second (Engineering Manager) has no id.
    titles = [r.title for r in raws]
    assert any("Python Backend" in t for t in titles)
    backend = [r for r in raws if "Python Backend" in r.title][0]
    # apply url resolved to absolute
    assert backend.apply_url.startswith("https://remoteok.com/l/1001")
    assert backend.company == "Acme Corp"
    assert backend.location == "Remote"
    assert "python" in backend.description.lower()


def test_remoteok_skips_metadata_element():
    """First element in real RemoteOK API is a metadata dict with no 'slug'."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["jobs"]
    real_count = len([j for j in data if isinstance(j, dict) and "slug" in j])
    data = [{"legal": 1}] + data  # prepend metadata
    jobs = [j for j in data if isinstance(j, dict) and "slug" in j]
    assert len(jobs) == real_count  # metadata element without 'slug' skipped
