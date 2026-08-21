from __future__ import annotations

import sqlite3

from jobharness import algo
from jobharness.dedupe import (
    SCHEMA_V3,
    SCHEMA_VERSION,
    DedupeStore,
    _legacy_job_id_hash,
    _store_block_key,
)
from jobharness.models import CLOSED, VALID_AUTHENTIC, Job, job_id_hash


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


def _legacy_v3_db(path, rows):
    """A pre-v4 DB: v3 schema, version marker '3', rows as given (each a
    tuple of (job_id_hash, title, company, location, apply_url_direct))."""
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_V3)
    conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('version','3')")
    for h, t, c, loc, u in rows:
        conn.execute(
            "INSERT INTO jobs (job_id_hash, title, company, location, apply_url_direct, "
            "first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?)",
            (h, t, c, loc, u, 1.0, 1.0),
        )
    conn.commit()
    conn.close()


def test_legacy_normalization_rows_rehashed_on_open(tmp_path):
    """Rows stored under the pre-v4 hash normalization (spaces kept in the
    normalized text) get job_id_hash/canonical_job_id/block_key recomputed on
    open, mirroring the insert path."""
    db = tmp_path / "t.db"
    _legacy_v3_db(
        db,
        [(_legacy_job_id_hash("Backend Engineer", "Acme", "Remote"),
          "Backend Engineer", "Acme", "Remote", "https://acme.com/j/1")],
    )
    store = DedupeStore(db)
    assert store.norm_migrated_count == 1
    assert store.norm_conflict_skipped == 0
    row = store.conn.execute("SELECT job_id_hash, canonical_job_id, block_key FROM jobs").fetchone()
    fresh = Job(title="Backend Engineer", company="Acme", location="Remote")
    fresh.apply_url_direct = "https://acme.com/j/1"
    assert row["job_id_hash"] == job_id_hash("Backend Engineer", "Acme", "Remote")
    assert row["canonical_job_id"] == fresh.compute_canonical_id()
    assert row["block_key"] == _store_block_key(algo.blocking_keys(fresh))
    cur = store.conn.execute("SELECT value FROM schema_meta WHERE key='version'")
    assert cur.fetchone()[0] == str(SCHEMA_VERSION)
    store.close()
    # version-gated: a second open is a no-op
    store2 = DedupeStore(db)
    assert store2.norm_migrated_count == 0
    store2.close()


def test_current_normalization_rows_untouched(tmp_path):
    """Rows already hashed with the current normalization are never rewritten,
    even when canonical_job_id/block_key look stale."""
    db = tmp_path / "t.db"
    h = job_id_hash("Backend Engineer", "Acme", "Remote")
    _legacy_v3_db(db, [(h, "Backend Engineer", "Acme", "Remote", None)])
    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE jobs SET canonical_job_id=?, block_key=?",
        ("url:https://acme.com/j/1", ";acme|remote;"),
    )
    conn.commit()
    conn.close()
    store = DedupeStore(db)
    assert store.norm_migrated_count == 0
    row = store.conn.execute("SELECT job_id_hash, canonical_job_id, block_key FROM jobs").fetchone()
    assert row["job_id_hash"] == h
    assert row["canonical_job_id"] == "url:https://acme.com/j/1"
    assert row["block_key"] == ";acme|remote;"
    store.close()


def test_legacy_rehash_skips_null_title(tmp_path):
    """Rows with a NULL title/company cannot be re-hashed: legacy hash stays."""
    db = tmp_path / "t.db"
    legacy = _legacy_job_id_hash(None, "Acme", "Remote")
    _legacy_v3_db(db, [(legacy, None, "Acme", "Remote", None)])
    store = DedupeStore(db)
    assert store.norm_migrated_count == 0
    row = store.conn.execute("SELECT job_id_hash FROM jobs").fetchone()
    assert row["job_id_hash"] == legacy
    store.close()


def test_legacy_rehash_pk_conflict_keeps_legacy_hash(tmp_path):
    """If the recomputed hash collides with an existing primary key the row is
    skipped (kept under its legacy hash) rather than erroring the open."""
    db = tmp_path / "t.db"
    h_b = job_id_hash("BackendEngineer", "Acme", "Remote")  # canonical under both norms
    h_a = _legacy_job_id_hash("Backend Engineer", "Acme", "Remote")  # must move onto h_b
    assert h_a != h_b
    _legacy_v3_db(
        db,
        [
            (h_b, "BackendEngineer", "Acme", "Remote", None),
            (h_a, "Backend Engineer", "Acme", "Remote", None),
        ],
    )
    store = DedupeStore(db)
    assert store.norm_migrated_count == 0
    assert store.norm_conflict_skipped == 1
    rows = store.conn.execute("SELECT job_id_hash, title FROM jobs ORDER BY rowid").fetchall()
    assert rows[0]["job_id_hash"] == h_b
    assert rows[1]["job_id_hash"] == h_a
    store.close()
