from __future__ import annotations

import sqlite3

from jobharness import algo
from jobharness.dedupe import DedupeStore
from jobharness.models import CLOSED, VALID_AUTHENTIC, Job


def make_job(source="remoteok", status=VALID_AUTHENTIC, description="python api backend"):
    j = Job(title="Backend Engineer", company="Acme", location="Remote")
    j.source_name = source
    j.apply_url_direct = "https://acme.com/j/1"
    j.description = description
    j.authentic_status = status
    j.compute_hash()
    return j


def test_closed_then_authentic_re_alerts(tmp_path):
    """(a) First seen CLOSED, later sighted AUTHENTIC -> genuinely_new=True."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job(status=CLOSED)
    assert store.upsert(a) is False
    assert a.genuinely_new is False
    b = make_job()
    b.job_id_hash = a.job_id_hash
    assert store.upsert(b) is True
    assert b.genuinely_new is True
    assert b.re_alerted is True
    row = store.conn.execute(
        "SELECT authentic_status FROM jobs WHERE job_id_hash=?", (a.job_id_hash,)
    ).fetchone()
    assert row["authentic_status"] == VALID_AUTHENTIC
    store.close()


def test_repeat_authentic_sighting_not_new(tmp_path):
    """(b) Repeat AUTHENTIC sighting -> genuinely_new=False (no re-alert)."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job()
    assert store.upsert(a) is True
    b = make_job(source="weworkremotely")
    assert store.upsert(b) is False
    assert b.genuinely_new is False
    assert b.re_alerted is False
    row = store.conn.execute(
        "SELECT authentic_status FROM jobs WHERE job_id_hash=?", (a.job_id_hash,)
    ).fetchone()
    assert row["authentic_status"] == VALID_AUTHENTIC
    store.close()


def test_repeat_closed_sighting_not_new(tmp_path):
    """CLOSED followed by CLOSED stays non-new; no re-alert fires."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job(status=CLOSED)
    assert store.upsert(a) is False
    b = make_job(status=CLOSED)
    b.job_id_hash = a.job_id_hash
    assert store.upsert(b) is False
    assert b.re_alerted is False
    store.close()


def test_stored_fields_refresh_on_repeat_sighting(tmp_path):
    """(c) Stored title/description/date_posted refresh on second sighting."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job(description="python api backend")
    assert store.upsert(a) is True
    b = make_job()
    b.job_id_hash = a.job_id_hash
    b.title = "Backend Engineer (Remote)"
    b.description = "python api backend full text"
    b.date_posted = "2026-08-21"
    assert store.upsert(b) is False
    row = store.conn.execute(
        "SELECT title, description, date_posted FROM jobs WHERE job_id_hash=?",
        (a.job_id_hash,),
    ).fetchone()
    assert row["title"] == "Backend Engineer (Remote)"
    assert row["description"] == "python api backend full text"
    assert row["date_posted"] == "2026-08-21"
    store.close()


def test_empty_incoming_does_not_clobber_stored_fields(tmp_path):
    """Refresh is non-empty only: empty incoming text keeps stored values."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job(description="python api backend")
    assert store.upsert(a) is True
    b = make_job()
    b.job_id_hash = a.job_id_hash
    b.title = ""
    b.description = ""
    b.date_posted = ""
    assert store.upsert(b) is False
    row = store.conn.execute(
        "SELECT title, description, date_posted FROM jobs WHERE job_id_hash=?",
        (a.job_id_hash,),
    ).fetchone()
    assert row["title"] == "Backend Engineer"
    assert row["description"] == "python api backend"
    store.close()


def test_merge_refreshes_stored_text_fields(tmp_path):
    """merge() refreshes non-empty text fields too (fuzzy linkage path)."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job()
    assert store.upsert(a) is True
    b = make_job(source="weworkremotely")
    b.job_id_hash = a.job_id_hash
    b.title = "Backend Engineer (Remote)"
    b.description = "python api backend full text"
    res = store.fuzzy_lookup(b)
    assert res["matched"] is True
    store.merge(b, res["existing_row"])
    row = store.conn.execute(
        "SELECT title, description FROM jobs WHERE job_id_hash=?", (a.job_id_hash,)
    ).fetchone()
    assert row["title"] == "Backend Engineer (Remote)"
    assert row["description"] == "python api backend full text"
    store.close()


def test_merge_closed_to_authentic_re_alerts(tmp_path):
    """merge() must fire the re-alert when the stored row is CLOSED and the
    incoming job is AUTHENTIC: exact-hash re-sightings reach merge, not
    upsert, so this is what makes the advertised re-alert reachable."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job(status=CLOSED)
    assert store.upsert(a) is False
    b = make_job()  # AUTHENTIC
    b.job_id_hash = a.job_id_hash
    res = store.fuzzy_lookup(b)
    assert res["matched"] is True
    store.merge(b, res["existing_row"])
    assert b.genuinely_new is True
    assert b.re_alerted is True
    row = store.conn.execute(
        "SELECT authentic_status FROM jobs WHERE job_id_hash=?", (a.job_id_hash,)
    ).fetchone()
    assert row["authentic_status"] == VALID_AUTHENTIC
    store.close()


def test_merge_authentic_to_authentic_not_re_alerted(tmp_path):
    """Non-recovery merge keeps the current semantics: no genuinely_new."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job()
    assert store.upsert(a) is True
    b = make_job(source="weworkremotely")
    b.job_id_hash = a.job_id_hash
    res = store.fuzzy_lookup(b)
    assert res["matched"] is True
    store.merge(b, res["existing_row"])
    assert b.genuinely_new is False
    assert b.re_alerted is False
    store.close()


def test_merge_closed_to_closed_not_re_alerted(tmp_path):
    """CLOSED -> CLOSED merge stays non-new; no re-alert fires."""
    store = DedupeStore(tmp_path / "t.db")
    a = make_job(status=CLOSED)
    assert store.upsert(a) is False
    b = make_job(status=CLOSED)
    b.job_id_hash = a.job_id_hash
    res = store.fuzzy_lookup(b)
    assert res["matched"] is True
    store.merge(b, res["existing_row"])
    assert b.genuinely_new is False
    assert b.re_alerted is False
    store.close()


def test_batched_commits_flush_persists(tmp_path):
    """(d) N upserts without flush are visible on the same connection; flush()
    persists so a fresh connection sees them."""
    db = tmp_path / "t.db"
    store = DedupeStore(db)
    n = 10
    for i in range(n):
        j = Job(title=f"Engineer {i}", company="Acme", location="Remote")
        j.source_name = "remoteok"
        j.compute_hash()
        assert store.upsert(j) is True
    assert store._pending == n
    row = store.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    assert row[0] == n
    store.flush()
    assert store._pending == 0
    store.close()
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == n
    finally:
        conn.close()


def test_close_flushes_pending(tmp_path):
    """close() persists pending writes without an explicit flush()."""
    db = tmp_path / "t.db"
    store = DedupeStore(db)
    for i in range(3):
        j = Job(title=f"Engineer {i}", company="Acme", location="Remote")
        j.source_name = "remoteok"
        j.compute_hash()
        store.upsert(j)
    store.close()
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3
    finally:
        conn.close()


def test_commit_every_constant():
    assert DedupeStore.COMMIT_EVERY == 50


def test_candidate_limit_constant():
    """(e) Candidate cap constant is 50."""
    assert DedupeStore.CANDIDATE_LIMIT == 50


def test_find_candidates_caps_at_candidate_limit(tmp_path):
    """Blocking-key bucketing: >50 rows sharing a bucket yield at most 50."""
    store = DedupeStore(tmp_path / "t.db")
    for i in range(60):
        j = Job(title=f"Engineer {i}", company="Acme", location="Remote")
        j.source_name = "remoteok"
        j.apply_url_direct = f"https://acme.com/j/{i}"
        j.compute_hash()
        j.block_key = algo.blocking_keys(j)
        store.upsert(j)
    q = Job(title="Engineer X", company="Acme", location="Remote")
    q.source_name = "remoteok"
    q.compute_hash()
    q.block_key = ["acme|remote"]
    candidates = store.find_candidates(q)
    assert len(candidates) == 50
    store.close()
