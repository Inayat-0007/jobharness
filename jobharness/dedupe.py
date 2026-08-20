from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .models import Job, VALID_AUTHENTIC

SCHEMA_VERSION = 2

SCHEMA_V2 = """
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
    apply_url_direct TEXT,
    first_seen_at REAL,
    last_seen_at REAL,
    seen_sources TEXT,
    authentic_status TEXT,
    confidence_score INTEGER DEFAULT 0,
    valid_through TEXT,
    employer_domain TEXT
);
"""


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
            cur.execute("DROP TABLE IF EXISTS jobs")
            self.conn.executescript(SCHEMA_V2)
            cur.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('version',?)", (str(SCHEMA_VERSION),))
            self.conn.commit()
            return
        # Existing v1 table: add missing columns idempotently.
        for stmt in (
            "ALTER TABLE jobs ADD COLUMN confidence_score INTEGER DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN valid_through TEXT",
            "ALTER TABLE jobs ADD COLUMN employer_domain TEXT",
        ):
            col = stmt.split("ADD COLUMN ")[1].split()[0]
            if col not in cols:
                try:
                    cur.execute(stmt)
                except sqlite3.OperationalError:
                    pass
        cur.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('version',?)", (str(SCHEMA_VERSION),))
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

    def upsert(self, job: Job) -> bool:
        """Return True if this job is genuinely new (first time seen, not CLOSED)."""
        cur = self.conn.cursor()
        cur.execute("SELECT first_seen_at, seen_sources FROM jobs WHERE job_id_hash=?", (job.job_id_hash,))
        row = cur.fetchone()
        now = time.time()
        if row is None:
            self.conn.execute(
                "INSERT INTO jobs (job_id_hash, title, company, location, role, experience_needed, "
                "date_posted, apply_url_direct, first_seen_at, last_seen_at, seen_sources, "
                "authentic_status, confidence_score, valid_through, employer_domain) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job.job_id_hash,
                    job.title,
                    job.company,
                    job.location,
                    job.role,
                    job.experience_needed,
                    job.date_posted,
                    job.apply_url_direct,
                    now,
                    now,
                    job.source_name,
                    job.authentic_status,
                    job.confidence_score,
                    job.valid_through,
                    job.employer_domain,
                ),
            )
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
        self.conn.execute(
            "UPDATE jobs SET last_seen_at=?, seen_sources=?, apply_url_direct=?, "
            "authentic_status=?, confidence_score=?, valid_through=?, employer_domain=? "
            "WHERE job_id_hash=?",
            (
                now,
                ",".join(job.seen_sources),
                job.apply_url_direct,
                job.authentic_status,
                job.confidence_score,
                job.valid_through,
                job.employer_domain,
                job.job_id_hash,
            ),
        )
        self.conn.commit()
        return False

    def close(self):
        self.conn.close()
