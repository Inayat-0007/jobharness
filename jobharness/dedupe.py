from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from . import algo
from .models import Job

SCHEMA_VERSION = 3

# v3 = v2 columns + identity/authenticity columns. `description` is stored so
# cross-run fuzzy comparison can score description similarity.
SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id_hash TEXT PRIMARY KEY,
    title TEXT,
    company TEXT,
    location TEXT,
    role TEXT,
    experience_needed TEXT,
    date_posted TEXT,
    description TEXT,
    apply_url_direct TEXT,
    first_seen_at REAL,
    last_seen_at REAL,
    seen_sources TEXT,
    authentic_status TEXT,
    confidence_score INTEGER DEFAULT 0,
    valid_through TEXT,
    employer_domain TEXT,
    canonical_job_id TEXT,
    block_key TEXT,
    possible_duplicate_of TEXT,
    identity_score REAL,
    authenticity_score REAL,
    match_score REAL,
    decision TEXT,
    matched_via TEXT DEFAULT 'exact',
    original_url TEXT,
    canonical_url TEXT,
    final_url TEXT,
    description_fingerprint TEXT,
    job_version INTEGER DEFAULT 1,
    posting_id TEXT,
    source_authority INTEGER,
    evidence TEXT,
    negative_evidence TEXT
);
"""

V3_MIGRATION_STATEMENTS = [
    "ALTER TABLE jobs ADD COLUMN confidence_score INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN valid_through TEXT",
    "ALTER TABLE jobs ADD COLUMN employer_domain TEXT",
    "ALTER TABLE jobs ADD COLUMN description TEXT",
    "ALTER TABLE jobs ADD COLUMN canonical_job_id TEXT",
    "ALTER TABLE jobs ADD COLUMN block_key TEXT",
    "ALTER TABLE jobs ADD COLUMN possible_duplicate_of TEXT",
    "ALTER TABLE jobs ADD COLUMN identity_score REAL",
    "ALTER TABLE jobs ADD COLUMN authenticity_score REAL",
    "ALTER TABLE jobs ADD COLUMN match_score REAL",
    "ALTER TABLE jobs ADD COLUMN decision TEXT",
    "ALTER TABLE jobs ADD COLUMN matched_via TEXT DEFAULT 'exact'",
    "ALTER TABLE jobs ADD COLUMN original_url TEXT",
    "ALTER TABLE jobs ADD COLUMN canonical_url TEXT",
    "ALTER TABLE jobs ADD COLUMN final_url TEXT",
    "ALTER TABLE jobs ADD COLUMN description_fingerprint TEXT",
    "ALTER TABLE jobs ADD COLUMN job_version INTEGER DEFAULT 1",
    "ALTER TABLE jobs ADD COLUMN posting_id TEXT",
    "ALTER TABLE jobs ADD COLUMN source_authority INTEGER",
    "ALTER TABLE jobs ADD COLUMN evidence TEXT",
    "ALTER TABLE jobs ADD COLUMN negative_evidence TEXT",
]

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_block_key ON jobs(block_key)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_canonical_job_id ON jobs(canonical_job_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_possible_duplicate_of ON jobs(possible_duplicate_of)",
]


def _store_val(v):
    """Serialize a Job attribute for a TEXT column (lists -> ','-joined)."""
    if isinstance(v, list):
        return ",".join(str(x) for x in v)
    return v


def _store_block_key(keys) -> str:
    """';'-delimited with wrapping so `LIKE '%;key;%'` lookups are exact
    (no substring false positives between similar keys)."""
    return ";" + ";".join(str(k) for k in (keys or []) if k) + ";"


class DedupeStore:
    def __init__(self, db_path: str | Path = "jobs.db", max_age_days: int = 90):
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._migrate()
        self._prune(max_age_days)

    def _migrate(self) -> None:
        cur = self.conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS jobs (job_id_hash TEXT, placeholder TEXT)")
        cur.execute("PRAGMA table_info(jobs)")
        cols = {r[1] for r in cur.fetchall()}
        if not cols or cols == {"job_id_hash", "placeholder"}:
            # v1 placeholder path: rebuild from scratch (now to v3).
            cur.execute("DROP TABLE IF EXISTS jobs")
            self.conn.executescript(SCHEMA_V3)
        else:
            # Existing v1/v2 table: add missing columns idempotently.
            for stmt in V3_MIGRATION_STATEMENTS:
                col = stmt.split("ADD COLUMN ")[1].split()[0]
                if col not in cols:
                    try:
                        cur.execute(stmt)
                    except sqlite3.OperationalError:
                        pass
        cur.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('version',?)", (str(SCHEMA_VERSION),))
        for stmt in INDEX_STATEMENTS:
            try:
                cur.execute(stmt)
            except sqlite3.OperationalError:
                pass
        self.conn.commit()

    def _prune(self, max_age_days: int) -> None:
        if max_age_days <= 0:
            return
        cutoff = time.time() - max_age_days * 86400
        try:
            self.conn.execute("DELETE FROM jobs WHERE last_seen_at < ? AND authentic_status=?", (cutoff, "CLOSED"))
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

    def _insert(self, job: Job, now: float) -> None:
        self.conn.execute(
            "INSERT INTO jobs (job_id_hash, title, company, location, role, experience_needed, "
            "date_posted, description, apply_url_direct, first_seen_at, last_seen_at, seen_sources, "
            "authentic_status, confidence_score, valid_through, employer_domain, "
            "canonical_job_id, block_key, possible_duplicate_of, identity_score, "
            "authenticity_score, match_score, decision, matched_via, original_url, "
            "canonical_url, final_url, description_fingerprint, job_version, posting_id, "
            "source_authority, evidence, negative_evidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job.job_id_hash,
                job.title,
                job.company,
                job.location,
                job.role,
                job.experience_needed,
                job.date_posted,
                job.description,
                job.apply_url_direct,
                now,
                now,
                job.source_name,
                job.authentic_status,
                job.confidence_score,
                job.valid_through,
                job.employer_domain,
                job.canonical_job_id,
                _store_block_key(job.block_key),
                job.possible_duplicate_of,
                job.identity_score,
                job.authenticity_score,
                job.match_score,
                job.decision,
                job.matched_via,
                job.original_url,
                job.canonical_url,
                job.final_url,
                job.description_fingerprint,
                job.job_version,
                job.posting_id,
                job.source_authority,
                _store_val(job.evidence),
                _store_val(job.negative_evidence),
            ),
        )

    def _update(self, job: Job, now: float) -> None:
        self.conn.execute(
            "UPDATE jobs SET last_seen_at=?, seen_sources=?, apply_url_direct=?, "
            "authentic_status=?, confidence_score=?, valid_through=?, employer_domain=?, "
            "canonical_job_id=?, block_key=?, possible_duplicate_of=?, identity_score=?, "
            "authenticity_score=?, match_score=?, decision=?, matched_via=?, original_url=?, "
            "canonical_url=?, final_url=?, description_fingerprint=?, job_version=?, posting_id=?, "
            "source_authority=?, evidence=?, negative_evidence=? WHERE job_id_hash=?",
            (
                now,
                ",".join(job.seen_sources),
                job.apply_url_direct,
                job.authentic_status,
                job.confidence_score,
                job.valid_through,
                job.employer_domain,
                job.canonical_job_id,
                _store_block_key(job.block_key),
                job.possible_duplicate_of,
                job.identity_score,
                job.authenticity_score,
                job.match_score,
                job.decision,
                job.matched_via,
                job.original_url,
                job.canonical_url,
                job.final_url,
                job.description_fingerprint,
                job.job_version,
                job.posting_id,
                job.source_authority,
                _store_val(job.evidence),
                _store_val(job.negative_evidence),
                job.job_id_hash,
            ),
        )

    def upsert(self, job: Job) -> bool:
        """Return True if this job is genuinely new (first time seen, not CLOSED).

        Stores all v3 columns; on repeat sight merges seen_sources as before.
        """
        cur = self.conn.cursor()
        cur.execute("SELECT first_seen_at, seen_sources FROM jobs WHERE job_id_hash=?", (job.job_id_hash,))
        row = cur.fetchone()
        now = time.time()
        if row is None:
            self._insert(job, now)
            job.first_seen_at = now
            # Only alert on new jobs that are not already closed.
            job.genuinely_new = job.authentic_status != "CLOSED"
            job.seen_sources = [job.source_name]
            self.conn.commit()
            return job.genuinely_new
        first_seen, seen_sources = row
        job.first_seen_at = first_seen
        job.genuinely_new = False
        srcs = (seen_sources or "").split(",")
        if job.source_name and job.source_name not in srcs:
            srcs.append(job.source_name)
        job.seen_sources = [s for s in srcs if s]
        self._update(job, now)
        self.conn.commit()
        return False

    def find_candidates(self, job: Job, limit: int = 25) -> list[sqlite3.Row]:
        """Lookup order: exact job_id_hash -> canonical_job_id -> canonical URL /
        posting_id -> rows matching any block_key (LIMIT-bounded)."""
        cur = self.conn.cursor()
        out: list[sqlite3.Row] = []
        seen: set[str] = set()

        def _collect(col: str, value) -> None:
            if not value:
                return
            for row in cur.execute(f"SELECT * FROM jobs WHERE {col}=?", (value,)).fetchall():
                if row["job_id_hash"] not in seen:
                    seen.add(row["job_id_hash"])
                    out.append(row)

        _collect("job_id_hash", job.job_id_hash)
        if len(out) >= limit:
            return out[:limit]
        _collect("canonical_job_id", job.canonical_job_id)
        if len(out) >= limit:
            return out[:limit]
        _collect("canonical_url", job.canonical_url)
        _collect("posting_id", job.posting_id)
        if len(out) >= limit:
            return out[:limit]
        block_keys = job.block_key or algo.blocking_keys(job)
        for bk in block_keys:
            if not bk:
                continue
            for row in cur.execute("SELECT * FROM jobs WHERE block_key LIKE ?", (f"%;{bk};%",)).fetchall():
                if row["job_id_hash"] not in seen:
                    seen.add(row["job_id_hash"])
                    out.append(row)
            if len(out) >= limit:
                break
        return out[:limit]

    def fuzzy_lookup(self, job: Job) -> dict:
        """Run algo.composite_similarity against find_candidates.

        Returns: {matched, matched_via, identity_score, possible_duplicate_of,
        decision_hint, existing_row}
        - auto_merge (HIGH) -> matched=True, decision_hint="AUTO_ACCEPT"
        - review (MEDIUM)  -> matched=False, decision_hint="REVIEW",
          possible_duplicate_of set
        - none (LOW)       -> no match
        """
        candidates = self.find_candidates(job)
        result = {
            "matched": False,
            "matched_via": "",
            "identity_score": 0.0,
            "possible_duplicate_of": "",
            "decision_hint": "",
            "existing_row": None,
        }
        if not candidates:
            return result
        best = None
        best_s = 0.0
        best_hint = ""
        for row in candidates:
            if job.job_id_hash and row["job_id_hash"] == job.job_id_hash:
                best = ("exact", row, 1.0, "AUTO_ACCEPT")
                break
            verdict, s = algo.composite_similarity(
                job.title,
                job.company,
                job.location,
                job.description,
                row["title"] or "",
                row["company"] or "",
                row["location"] or "",
                row["description"] or "",
                domain1=job.employer_domain,
                domain2=row["employer_domain"] or "",
                url1=job.apply_url_direct,
                url2=row["apply_url_direct"] or "",
            )
            hint = {
                "auto_merge": "AUTO_ACCEPT",
                "review": "REVIEW",
                "none": "",
            }[verdict]
            if s > best_s:
                best_s = s
                best = ("fuzzy", row, s, hint)
                best_hint = hint
        via, row, score, hint = best
        result["identity_score"] = score
        result["possible_duplicate_of"] = row["job_id_hash"]
        result["existing_row"] = row
        if via == "exact" or hint:
            result["matched_via"] = via
            result["decision_hint"] = hint
            if hint == "AUTO_ACCEPT":
                result["matched"] = True
        return result

    def merge(self, job: Job, existing_row: sqlite3.Row) -> None:
        """Merge an incoming job into an existing stored row (exact or fuzzy
        match): update last_seen_at, append seen_sources, refresh mutable
        fields. Does NOT set genuinely_new and never inserts a new row."""
        now = time.time()
        job.first_seen_at = existing_row["first_seen_at"]
        job.genuinely_new = False
        srcs = (existing_row["seen_sources"] or "").split(",")
        if job.source_name and job.source_name not in srcs:
            srcs.append(job.source_name)
        job.seen_sources = [s for s in srcs if s]
        self.conn.execute(
            "UPDATE jobs SET last_seen_at=?, seen_sources=?, apply_url_direct=?, "
            "authentic_status=?, confidence_score=?, valid_through=?, employer_domain=?, "
            "canonical_job_id=?, block_key=?, possible_duplicate_of=?, identity_score=?, "
            "authenticity_score=?, match_score=?, decision=?, matched_via=?, original_url=?, "
            "canonical_url=?, final_url=?, description_fingerprint=?, job_version=?, posting_id=?, "
            "source_authority=?, evidence=?, negative_evidence=? WHERE job_id_hash=?",
            (
                now,
                ",".join(job.seen_sources),
                job.apply_url_direct,
                job.authentic_status,
                job.confidence_score,
                job.valid_through,
                job.employer_domain,
                job.canonical_job_id,
                _store_block_key(job.block_key),
                job.possible_duplicate_of,
                job.identity_score,
                job.authenticity_score,
                job.match_score,
                job.decision,
                job.matched_via,
                job.original_url,
                job.canonical_url,
                job.final_url,
                job.description_fingerprint,
                job.job_version,
                job.posting_id,
                job.source_authority,
                _store_val(job.evidence),
                _store_val(job.negative_evidence),
                existing_row["job_id_hash"],
            ),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
