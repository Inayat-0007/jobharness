from __future__ import annotations

import time

from jobharness import verify_cache


def test_roundtrip_ok_and_closed(tmp_path):
    db = tmp_path / "jobs.db"
    verify_cache.configure(db)
    try:
        assert verify_cache.lookup("https://acme.com/j/1") is None

        verify_cache.record("https://acme.com/j/1", "ok", 200)
        hit = verify_cache.lookup("https://acme.com/j/1")
        assert hit is not None
        assert hit["status"] == "ok"
        assert hit["status_code"] == 200

        verify_cache.record("https://acme.com/j/1", "closed", 404, "https://acme.com/gone")
        hit = verify_cache.lookup("https://acme.com/j/1")
        assert hit["status"] == "closed"
        assert hit["status_code"] == 404
        assert hit["redirect_to"] == "https://acme.com/gone"
    finally:
        verify_cache.close()


def test_transient_results_never_cached(tmp_path):
    db = tmp_path / "jobs.db"
    verify_cache.configure(db)
    try:
        verify_cache.record("https://acme.com/j/x", "degraded", 429)
        verify_cache.record("https://acme.com/j/x", "", 500)
        assert verify_cache.lookup("https://acme.com/j/x") is None
    finally:
        verify_cache.close()


def test_stale_ok_entry_expires(tmp_path):
    db = tmp_path / "jobs.db"
    verify_cache.configure(db)
    try:
        verify_cache.record("https://acme.com/j/stale", "ok", 200)
        with verify_cache._lock:
            verify_cache._conn.execute(
                "UPDATE verify_cache SET checked_at=? WHERE url=?",
                (time.time() - verify_cache.OK_TTL_S - 60, "https://acme.com/j/stale"),
            )
            verify_cache._conn.commit()
        assert verify_cache.lookup("https://acme.com/j/stale") is None
    finally:
        verify_cache.close()


def test_closed_ttl_longer_than_ok_ttl():
    assert verify_cache.CLOSED_TTL_S > verify_cache.OK_TTL_S


def test_disabled_cache_returns_none(tmp_path):
    verify_cache.close()
    assert verify_cache.lookup("https://x.test/j") is None
    verify_cache.record("https://x.test/j", "ok", 200)  # must not raise
    assert verify_cache.lookup("https://x.test/j") is None


def test_configure_none_or_repeated_is_safe(tmp_path):
    request_db = tmp_path / "jobs.db"
    verify_cache.configure(request_db)
    verify_cache.configure(request_db)  # idempotent
    assert verify_cache.lookup("https://x.test/j") is None
    verify_cache.configure(None)
    assert verify_cache.lookup("https://x.test/j") is None
    verify_cache.close()
