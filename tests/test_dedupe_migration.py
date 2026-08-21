from __future__ import annotations

import sqlite3

from jobharness.dedupe import SCHEMA_VERSION, DedupeStore
from jobharness.models import CLOSED, VALID_AUTHENTIC, Job


def make_job(source="remoteok"):
    j = Job(title="Backend Engineer", company="Acme", location="Remote")
    j.source_name = source
    j.apply_url_direct = "https://acme.com/j/1"
    j.authentic_status = VALID_AUTHENTIC
    j.confidence_score = 70
    j.valid_through = "2099-12-31"
    j.employer_domain = "acme.com"
    j.compute_hash()
    return j


def test_v1_to_v2_migration_adds_columns(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE jobs (job_id_hash TEXT, placeholder TEXT)")
    conn.execute("INSERT INTO jobs VALUES ('x','y')")
    conn.commit()
    conn.close()
    store = DedupeStore(db)
    cur = store.conn.cursor()
    cur.execute("PRAGMA table_info(jobs)")
    cols = {r[1] for r in cur.fetchall()}
    assert "confidence_score" in cols
    assert "valid_through" in cols
    assert "employer_domain" in cols
    cur.execute("SELECT value FROM schema_meta WHERE key='version'")
    assert cur.fetchone()[0] == str(SCHEMA_VERSION)
    store.close()


def test_closed_job_not_marked_genuinely_new(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    job = make_job()
    job.authentic_status = CLOSED
    assert store.upsert(job) is False
    assert job.genuinely_new is False
    store.close()


def test_first_insert_new_only_if_authentic(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    job = make_job()
    assert store.upsert(job) is True
    assert job.genuinely_new is True
    # second insert not new
    job2 = make_job(source="weworkremotely")
    assert store.upsert(job2) is False
    store.close()


def test_purge_old_closed(tmp_path):
    store = DedupeStore(tmp_path / "t.db", max_age_days=1)
    job = make_job()
    job.authentic_status = CLOSED
    store.upsert(job)
    # backdate last_seen_at beyond the 1-day window
    store.conn.execute("UPDATE jobs SET last_seen_at=?", (0,))
    store.conn.commit()
    store2 = DedupeStore(tmp_path / "t.db", max_age_days=1)
    cur = store2.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM jobs WHERE authentic_status=?", ("CLOSED",))
    assert cur.fetchone()[0] == 0
    store2.close()
