from __future__ import annotations

import sqlite3

from jobharness import algo
from jobharness.dedupe import SCHEMA_VERSION, DedupeStore
from jobharness.models import VALID_AUTHENTIC, Job

V3_COLUMNS = [
    "canonical_job_id", "block_key", "possible_duplicate_of", "identity_score",
    "authenticity_score", "match_score", "decision", "matched_via",
    "original_url", "canonical_url", "final_url", "description_fingerprint",
    "job_version", "posting_id", "source_authority", "evidence",
    "negative_evidence", "description",
]


def make_job(source="remoteok", **kw):
    j = Job(title="Backend Engineer", company="Acme", location="Remote")
    j.source_name = source
    j.apply_url_direct = "https://acme.com/j/1"
    j.description = "python api backend"
    j.authentic_status = VALID_AUTHENTIC
    j.confidence_score = 70
    j.compute_hash()
    j.canonical_job_id = j.compute_canonical_id()
    j.block_key = algo.blocking_keys(j)
    for k, v in kw.items():
        setattr(j, k, v)
    return j


def _v2_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE jobs (
            job_id_hash TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT,
            role TEXT, experience_needed TEXT, date_posted TEXT, apply_url_direct TEXT,
            first_seen_at REAL, last_seen_at REAL, seen_sources TEXT,
            authentic_status TEXT, confidence_score INTEGER DEFAULT 0,
            valid_through TEXT, employer_domain TEXT
        );
        INSERT INTO schema_meta VALUES ('version', '2');
        INSERT INTO jobs (job_id_hash, title, company)
        VALUES ('h1', 'Backend Engineer', 'Acme');
        """
    )
    conn.commit()
    conn.close()


def test_v2_table_migrates_to_v3(tmp_path):
    db = tmp_path / "t.db"
    _v2_db(db)
    store = DedupeStore(db)
    cur = store.conn.cursor()
    cur.execute("PRAGMA table_info(jobs)")
    cols = {r[1] for r in cur.fetchall()}
    for c in V3_COLUMNS:
        assert c in cols
    cur.execute("SELECT value FROM schema_meta WHERE key='version'")
    assert cur.fetchone()[0] == str(SCHEMA_VERSION)
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_jobs_block_key'")
    assert cur.fetchone() is not None
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_jobs_canonical_job_id'")
    assert cur.fetchone() is not None
    # existing row survived the migration
    cur.execute("SELECT title FROM jobs WHERE job_id_hash='h1'")
    assert cur.fetchone()[0] == "Backend Engineer"
    store.close()


def test_v1_placeholder_rebuilds_to_v3(tmp_path):
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
    assert "description" in cols
    assert "canonical_job_id" in cols
    assert "posting_id" in cols
    cur.execute("SELECT value FROM schema_meta WHERE key='version'")
    assert cur.fetchone()[0] == str(SCHEMA_VERSION)
    store.close()


def test_upsert_stores_new_columns(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    j = make_job()
    j.canonical_url = "https://acme.com/j/1"
    j.canonical_job_id = "url:https://acme.com/j/1"
    j.block_key = ["acme|backend engineer", "acme|remote"]
    j.identity_score = 0.9
    j.authenticity_score = 70.0
    j.match_score = 0.6
    j.decision = "AUTO_ACCEPT"
    j.matched_via = "exact"
    j.posting_id = "gh_1"
    j.description_fingerprint = "abc"
    j.source_authority = 5
    j.evidence = ["official_ats"]
    j.negative_evidence = []
    assert store.upsert(j) is True
    row = store.conn.execute("SELECT * FROM jobs WHERE job_id_hash=?", (j.job_id_hash,)).fetchone()
    assert row["canonical_job_id"] == "url:https://acme.com/j/1"
    assert row["block_key"] == ";acme|backend engineer;acme|remote;"
    assert row["decision"] == "AUTO_ACCEPT"
    assert row["evidence"] == "official_ats"
    assert row["posting_id"] == "gh_1"
    assert row["description"] == "python api backend"
    assert row["job_version"] == 1
    store.close()


def test_repeat_upsert_refreshes_v3_fields(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    a = make_job()
    assert store.upsert(a) is True
    b = make_job(source="weworkremotely")
    b.decision = "AUTO_ACCEPT"
    b.identity_score = 0.99
    assert store.upsert(b) is False
    row = store.conn.execute("SELECT * FROM jobs WHERE job_id_hash=?", (a.job_id_hash,)).fetchone()
    assert row["decision"] == "AUTO_ACCEPT"
    assert row["identity_score"] == 0.99
    assert "remoteok" in row["seen_sources"]
    assert "weworkremotely" in row["seen_sources"]
    store.close()


def test_fuzzy_lookup_rewritten_title_high(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    a = make_job()
    assert store.upsert(a) is True
    b = make_job()
    b.title = "Backend Engineer (Remote)"
    b.compute_hash()
    res = store.fuzzy_lookup(b)
    assert res["matched"] is True
    assert res["matched_via"] == "fuzzy"
    assert res["decision_hint"] == "AUTO_ACCEPT"
    assert res["identity_score"] >= 0.88
    assert res["possible_duplicate_of"] == a.job_id_hash
    store.close()


def test_fuzzy_lookup_medium_review(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    a = make_job()
    assert store.upsert(a) is True
    b = make_job()
    b.location = "Austin, TX"
    b.compute_hash()
    res = store.fuzzy_lookup(b)
    assert res["matched"] is False
    assert res["decision_hint"] == "REVIEW"
    assert res["possible_duplicate_of"] == a.job_id_hash
    store.close()


def test_fuzzy_lookup_distinct_job_not_matched(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    a = make_job()
    assert store.upsert(a) is True
    b = make_job()
    b.title = "Data Analyst"
    b.company = "Globex"
    b.location = "New York"
    b.description = "sql dashboards excel"
    b.apply_url_direct = "https://globex.com/j/9"
    b.compute_hash()
    res = store.fuzzy_lookup(b)
    assert res["matched"] is False
    assert res["decision_hint"] == ""
    assert res["matched_via"] == ""
    store.close()


def test_fuzzy_lookup_title_floor_not_matched(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    a = make_job()
    assert store.upsert(a) is True
    b = make_job()
    b.title = "Data Analyst"
    b.description = "sql dashboards excel"
    b.compute_hash()
    res = store.fuzzy_lookup(b)
    assert res["matched"] is False
    assert res["decision_hint"] == ""
    store.close()


def test_merge_updates_row_without_inserting(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    a = make_job(source="remoteok")
    assert store.upsert(a) is True
    b = make_job(source="weworkremotely")
    b.title = "Backend Engineer (Remote)"
    b.compute_hash()
    res = store.fuzzy_lookup(b)
    assert res["matched"] is True
    store.merge(b, res["existing_row"])
    assert b.genuinely_new is False
    assert b.first_seen_at == a.first_seen_at
    cur = store.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM jobs")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT seen_sources FROM jobs WHERE job_id_hash=?", (a.job_id_hash,))
    srcs = cur.fetchone()[0]
    assert "remoteok" in srcs
    assert "weworkremotely" in srcs
    store.close()
