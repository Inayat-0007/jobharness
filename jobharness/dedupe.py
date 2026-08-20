from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from .models import Job

SCHEMA = """
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
    authentic_status TEXT
);
"""


class DedupeStore:
    def __init__(self, db_path: str | Path = "jobs.db"):
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert(self, job: Job) -> bool:
        """Return True if this job is genuinely new (first time seen)."""
        cur = self.conn.cursor()
        cur.execute("SELECT first_seen_at, seen_sources FROM jobs WHERE job_id_hash=?", (job.job_id_hash,))
        row = cur.fetchone()
        now = time.time()
        if row is None:
            self.conn.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                ),
            )
            job.first_seen_at = now
            job.genuinely_new = True
            job.seen_sources = [job.source_name]
            self.conn.commit()
            return True
        first_seen, seen_sources = row
        job.first_seen_at = first_seen
        job.genuinely_new = False
        srcs = (seen_sources or "").split(",")
        if job.source_name and job.source_name not in srcs:
            srcs.append(job.source_name)
        job.seen_sources = [s for s in srcs if s]
        self.conn.execute(
            "UPDATE jobs SET last_seen_at=?, seen_sources=?, apply_url_direct=?, authentic_status=? WHERE job_id_hash=?",
            (now, ",".join(job.seen_sources), job.apply_url_direct, job.authentic_status, job.job_id_hash),
        )
        self.conn.commit()
        return False

    def close(self):
        self.conn.close()
