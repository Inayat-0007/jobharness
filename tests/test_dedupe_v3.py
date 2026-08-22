from __future__ import annotations

import sqlite3

from jobharness import algo
from jobharness.dedupe import SCHEMA_VERSION, DedupeStore
from jobharness.models import VALID_AUTHENTIC, Job
from jobharness.scoring.thresholds import MIN_UNCERTAIN_IDENTITY

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


def test_backfill_descriptions_from_reports(tmp_path):
    """Pre-v3 rows (NULL description) get backfilled from the latest report."""

    from jobharness.report import write_reports

    db = tmp_path / "t.db"
    store = DedupeStore(db)
    j = make_job()
    assert store.upsert(j) is True
    # simulate a pre-v3 row: description was never stored
    store.conn.execute("UPDATE jobs SET description=NULL WHERE job_id_hash=?", (j.job_id_hash,))
    store.conn.commit()
    store.close()

    # write a report containing the description (latest run wins)
    j2 = make_job()
    j2.description = "python api backend full text"
    j2.compute_hash()
    write_reports([j2], tmp_path / "reports", run_ts="20260821-000000")

    store = DedupeStore(db, reports_dir=tmp_path / "reports")
    row = store.conn.execute(
        "SELECT description FROM jobs WHERE job_id_hash=?", (j.job_id_hash,)
    ).fetchone()
    assert row["description"] == "python api backend full text"
    store.close()


def test_backfill_skips_without_reports_dir(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    j = make_job()
    assert store.upsert(j) is True
    store.conn.execute("UPDATE jobs SET description=NULL WHERE job_id_hash=?", (j.job_id_hash,))
    store.conn.commit()
    store.close()

    store = DedupeStore(tmp_path / "t.db")  # no reports_dir -> no-op
    row = store.conn.execute(
        "SELECT description FROM jobs WHERE job_id_hash=?", (j.job_id_hash,)
    ).fetchone()
    assert row["description"] is None
    store.close()


def test_fuzzy_lookup_prefers_review_candidate_over_higher_scoring_none(tmp_path):
    desc_in = "Python developer with Django PostgreSQL AWS experience backend API development"
    desc_a = "Python developer with Django PostgreSQL AWS experience backend API development plus occasional mentoring of junior engineers"
    title_a = "Backend Engineer (Remote)"
    title_b = "Software Engineer"

    # incoming job
    incoming = Job(title="Backend Engineer", company="Acme", location="Remote")
    incoming.description = desc_in
    incoming.apply_url_direct = "https://acme.com/j/1"
    incoming.authentic_status = VALID_AUTHENTIC
    incoming.confidence_score = 70
    incoming.compute_hash()
    incoming.canonical_job_id = incoming.compute_canonical_id()
    incoming.block_key = algo.blocking_keys(incoming)

    # rowA: near-identical title (distinct hash so the exact-match branch is
    # not taken), same company/location, partial desc overlap -> "review" verdict
    rowA = Job(title=title_a, company="Acme", location="Remote")
    rowA.description = desc_a
    rowA.apply_url_direct = "https://acme.com/j/2"
    rowA.authentic_status = VALID_AUTHENTIC
    rowA.confidence_score = 70
    rowA.compute_hash()
    rowA.canonical_job_id = rowA.compute_canonical_id()
    rowA.block_key = algo.blocking_keys(rowA)

    # rowB: different title (s_title < 0.75), same company/location/desc -> higher score, "none" verdict
    rowB = Job(title=title_b, company="Acme", location="Remote")
    rowB.description = desc_in
    rowB.apply_url_direct = "https://acme.com/j/3"
    rowB.authentic_status = VALID_AUTHENTIC
    rowB.confidence_score = 70
    rowB.compute_hash()
    rowB.canonical_job_id = rowB.compute_canonical_id()
    rowB.block_key = algo.blocking_keys(rowB)

    # Precondition checks
    v_a, s_a = algo.composite_similarity(
        incoming.title, incoming.company, incoming.location, incoming.description,
        rowA.title, rowA.company, rowA.location, rowA.description,
        url1=incoming.apply_url_direct, url2=rowA.apply_url_direct,
    )
    assert v_a == "review", f"rowA verdict should be review, got {v_a}"
    assert 0.80 <= s_a < 0.88, f"rowA score {s_a} should be in [0.80, 0.88)"

    v_b, s_b = algo.composite_similarity(
        incoming.title, incoming.company, incoming.location, incoming.description,
        rowB.title, rowB.company, rowB.location, rowB.description,
        url1=incoming.apply_url_direct, url2=rowB.apply_url_direct,
    )
    assert v_b == "none", f"rowB verdict should be none, got {v_b}"
    assert s_b > s_a, f"rowB score {s_b} should exceed rowA score {s_a}"

    store = DedupeStore(tmp_path / "t.db")
    assert store.upsert(rowA) is True
    assert store.upsert(rowB) is True

    result = store.fuzzy_lookup(incoming)
    assert result["decision_hint"] == "REVIEW"
    assert result["possible_duplicate_of"] == rowA.job_id_hash
    assert result["matched"] is False
    assert result["matched_via"] == "fuzzy"
    assert result["identity_score"] == round(s_b, 4)
    assert result["existing_row"]["job_id_hash"] == rowA.job_id_hash
    store.close()

def test_fuzzy_lookup_strong_none_candidate_reports_identity_score(tmp_path):
    # All candidates verdict "none" (title-floor failure) but with a strong
    # composite score: identity evidence must be preserved (not 0.0, which
    # decide() would read as "no known duplicates" and could AUTO_ACCEPT),
    # while the job stays unmatched.
    desc_in = "Python developer with Django PostgreSQL AWS experience backend API development"
    title_b = "Software Engineer"

    incoming = Job(title="Backend Engineer", company="Acme", location="Remote")
    incoming.description = desc_in
    incoming.apply_url_direct = "https://acme.com/j/1"
    incoming.authentic_status = VALID_AUTHENTIC
    incoming.confidence_score = 70
    incoming.compute_hash()
    incoming.canonical_job_id = incoming.compute_canonical_id()
    incoming.block_key = algo.blocking_keys(incoming)

    # rowB: different title (below TITLE_FLOOR -> "none"), identical
    # company/location/description -> strong composite score.
    rowB = Job(title=title_b, company="Acme", location="Remote")
    rowB.description = desc_in
    rowB.apply_url_direct = "https://acme.com/j/3"
    rowB.authentic_status = VALID_AUTHENTIC
    rowB.confidence_score = 70
    rowB.compute_hash()
    rowB.canonical_job_id = rowB.compute_canonical_id()
    rowB.block_key = algo.blocking_keys(rowB)

    v_b, s_b = algo.composite_similarity(
        incoming.title, incoming.company, incoming.location, incoming.description,
        rowB.title, rowB.company, rowB.location, rowB.description,
        url1=incoming.apply_url_direct, url2=rowB.apply_url_direct,
    )
    assert v_b == "none", f"rowB verdict should be none, got {v_b}"
    assert s_b >= MIN_UNCERTAIN_IDENTITY, (
        f"rowB score {s_b} should be >= MIN_UNCERTAIN_IDENTITY ({MIN_UNCERTAIN_IDENTITY})"
    )

    store = DedupeStore(tmp_path / "t.db")
    assert store.upsert(rowB) is True

    result = store.fuzzy_lookup(incoming)
    assert result["matched"] is False
    assert result["decision_hint"] == ""
    assert result["matched_via"] == ""
    assert result["identity_score"] == round(s_b, 4)
    store.close()
