from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from . import algo
from .logging import get_logger
from .models import CLOSED, MISSING, VALID_AUTHENTIC, Job, job_id_hash
from .scoring.thresholds import MIN_UNCERTAIN_IDENTITY

SCHEMA_VERSION = 4

# Batched commits: writes are committed every COMMIT_EVERY ops (or on flush()/
# close()). WAL is enabled, so uncommitted writes are durable and visible to
# reads on the same connection.
COMMIT_EVERY = 50

# Transient "database is locked" (SQLITE_BUSY) failures retry up to
# _LOCK_RETRIES times with _LOCK_BACKOFF seconds between attempts.
_LOCK_RETRIES = 3
_LOCK_BACKOFF = 0.2

# _backfill_descriptions() re-parses every reports/*/report.json when any
# stored row lacks a description; guard so it runs at most once per process.
_BACKFILL_RUN = False

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

# Columns find_candidates() may filter on. Lookups are whitelisted here so no
# caller-controlled string ever reaches SQL interpolation.
_CANDIDATE_COLUMNS = {
    "job_id_hash": "job_id_hash",
    "canonical_job_id": "canonical_job_id",
    "canonical_url": "canonical_url",
    "posting_id": "posting_id",
}


def _store_val(v):
    """Serialize a Job attribute for a TEXT column (lists -> ','-joined)."""
    if isinstance(v, list):
        return ",".join(str(x) for x in v)
    return v


def _store_block_key(keys) -> str:
    """';'-delimited with wrapping so `LIKE '%;key;%'` lookups are exact
    (no substring false positives between similar keys)."""
    return ";" + ";".join(str(k) for k in (keys or []) if k) + ";"


def _refresh_val(v):
    """Return the incoming value for a text-column refresh, or None when it
    must NOT overwrite the stored value (empty or the MISSING sentinel).
    Used with `COALESCE(?, col)` so stored text survives empty re-sightings."""
    if v is None:
        return None
    s = str(v)
    if s.strip() == "" or s == MISSING:
        return None
    return v


def _legacy_norm(text) -> str:
    """The pre-v4 job_id_hash normalization: models._norm without the final
    space-strip, so single spaces are kept ('Backend Engineer' -> 'backend
    engineer'). Rows hashed before that change cannot be found by the new
    hash, so the v4 migration re-identifies them with this helper."""
    if not text:
        return ""
    text = str(text).strip().lower()
    text = text.replace("++", "pp")
    text = re.sub(r"(?<=[a-z0-9])#", "sharp", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[^a-z0-9 ]+", "", text)


def _legacy_job_id_hash(title, company, location="") -> str:
    raw = f"{_legacy_norm(title)}|{_legacy_norm(company)}|{_legacy_norm(location)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# The refresh UPDATE shared by _update() and merge() (30 SET columns plus the
# WHERE job_id_hash placeholder). job_id_hash (the key) is never rewritten;
# text columns are COALESCE-refreshed so empty incoming values leave stored
# text untouched.
_UPDATE_SQL = (
    "UPDATE jobs SET last_seen_at=?, seen_sources=?, title=COALESCE(?, title), "
    "company=COALESCE(?, company), location=COALESCE(?, location), "
    "role=COALESCE(?, role), date_posted=COALESCE(?, date_posted), "
    "description=COALESCE(?, description), apply_url_direct=?, "
    "authentic_status=?, confidence_score=?, valid_through=?, employer_domain=?, "
    "canonical_job_id=?, block_key=?, possible_duplicate_of=?, identity_score=?, "
    "authenticity_score=?, match_score=?, decision=?, matched_via=?, original_url=?, "
    "canonical_url=?, final_url=?, description_fingerprint=?, job_version=?, posting_id=?, "
    "source_authority=?, evidence=?, negative_evidence=? WHERE job_id_hash=?"
)


def _update_params(job: Job, now: float) -> tuple:
    """The _UPDATE_SQL bind values in column order. The trailing WHERE
    job_id_hash placeholder is filled in by the caller (the stored key for
    merge, the incoming hash for upsert)."""
    return (
        now,
        ",".join(job.seen_sources),
        _refresh_val(job.title),
        _refresh_val(job.company),
        _refresh_val(job.location),
        _refresh_val(job.role),
        _refresh_val(job.date_posted),
        _refresh_val(job.description),
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
    )


_log = get_logger("dedupe")


class DedupeStore:
    # Bucketed candidate scan cap per incoming job (find_candidates).
    CANDIDATE_LIMIT = 50
    # Writes are committed every COMMIT_EVERY ops (or on flush()/close()).
    COMMIT_EVERY = COMMIT_EVERY

    def __init__(
        self,
        db_path: str | Path = "jobs.db",
        max_age_days: int = 90,
        reports_dir: str | Path | None = None,
    ):
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        # Overlapping runs must not crash with 'database is locked': wait up to
        # 30s for a lock, and WAL lets readers/writers coexist.
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._pending = 0
        self.norm_migrated_count = 0
        self.norm_conflict_skipped = 0
        self._migrate()
        self._backfill_descriptions(reports_dir)
        self._prune(max_age_days)

    def _backfill_descriptions(self, reports_dir) -> None:
        """Fill NULL/empty `description` from the latest matching row in
        `reports/*/report.json`.

        Pre-v3 rows were stored without a description, which starves fuzzy
        merge for old rows (description similarity is a composite input).
        Runs at most once per process (module flag); newest report run wins
        per job_id_hash.
        """
        global _BACKFILL_RUN
        if _BACKFILL_RUN:
            return
        if not reports_dir:
            return
        rd = Path(reports_dir)
        if not rd.is_dir():
            return
        _BACKFILL_RUN = True
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT job_id_hash FROM jobs WHERE description IS NULL OR description=''"
        ).fetchall()
        if not rows:
            return
        descriptions: dict[str, str] = {}
        for run_dir in sorted(rd.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            jf = run_dir / "report.json"
            if not jf.exists():
                continue
            try:
                parsed = json.loads(jf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for j in parsed:
                h = j.get("job_id_hash")
                desc = j.get("description")
                if h and desc and h not in descriptions:
                    descriptions[h] = desc
        updated = 0
        for row in rows:
            desc = descriptions.get(row["job_id_hash"])
            if desc:
                cur.execute(
                    "UPDATE jobs SET description=? WHERE job_id_hash=?",
                    (desc, row["job_id_hash"]),
                )
                updated += 1
        if updated:
            self.conn.commit()

    def _migrate(self) -> None:
        cur = self.conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS jobs (job_id_hash TEXT, placeholder TEXT)")
        cur.execute("PRAGMA table_info(jobs)")
        cols = {r[1] for r in cur.fetchall()}
        if not cols or cols == {"job_id_hash", "placeholder"}:
            # v1 placeholder path: rebuild from scratch (now to v3). Back the
            # file up first in case it ever held unexpected legacy data. WAL is
            # active, so checkpoint first (committed pages may still live in
            # the -wal file) and copy any leftover -wal alongside.
            try:
                import shutil
                import time as _t

                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                backup = f"{self.path}.legacy-{int(_t.time())}.bak"
                shutil.copyfile(self.path, backup)
                wal = self.path + "-wal"
                if os.path.exists(wal) and os.path.getsize(wal) > 0:
                    shutil.copyfile(wal, backup + "-wal")
                _log.warning("backed up legacy DB to %s before schema rebuild", backup)
            except OSError:
                pass
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
        stored_version = 0
        cur.execute("SELECT value FROM schema_meta WHERE key='version'")
        v_row = cur.fetchone()
        if v_row is not None:
            try:
                stored_version = int(v_row[0])
            except (TypeError, ValueError):
                stored_version = 0
        if stored_version < 4:
            self.norm_migrated_count = self._migrate_legacy_hashes()
            if self.norm_migrated_count:
                _log.info(
                    "re-hashed %d row(s) to the current job_id_hash normalization "
                    "(legacy space-preserving hashes)",
                    self.norm_migrated_count,
                )
            if self.norm_conflict_skipped:
                _log.warning(
                    "%d legacy row(s) kept their old hash: re-hash collided with "
                    "an existing primary key",
                    self.norm_conflict_skipped,
                )
        cur.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('version',?)", (str(SCHEMA_VERSION),))
        for stmt in INDEX_STATEMENTS:
            try:
                cur.execute(stmt)
            except sqlite3.OperationalError:
                pass
        self.conn.commit()

    def _migrate_legacy_hashes(self) -> int:
        """One-time re-identification of rows stored under the pre-v4
        job_id_hash normalization (models._norm used to keep single spaces).

        For every row whose stored hash equals the legacy hash of its own
        fields (and differs from the current canonical hash), rewrite
        job_id_hash, canonical_job_id and block_key exactly as the insert path
        would (Job built from the stored columns -> compute_canonical_id() +
        algo.blocking_keys()). Rows already canonical are untouched; rows with
        a NULL title/company are skipped (the legacy hash cannot be trusted);
        rows whose new hash would collide with another row's primary key keep
        their legacy hash. Returns the number of rows migrated; the number of
        conflict skips is exposed on self.norm_conflict_skipped."""
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT rowid, job_id_hash, title, company, location, posting_id, "
            "canonical_url, employer_domain, apply_url_direct FROM jobs ORDER BY rowid"
        ).fetchall()
        migrated = 0
        self.norm_conflict_skipped = 0
        for row in rows:
            title, company, location = row["title"], row["company"], row["location"]
            if title is None or company is None:
                continue
            legacy_hash = _legacy_job_id_hash(title, company, location)
            new_hash = job_id_hash(title, company, location)
            if row["job_id_hash"] != legacy_hash or row["job_id_hash"] == new_hash:
                continue
            job = Job(title=title, company=company, location=location)
            job.posting_id = row["posting_id"]
            job.canonical_url = row["canonical_url"]
            job.employer_domain = row["employer_domain"]
            job.apply_url_direct = row["apply_url_direct"]
            canonical_id = job.compute_canonical_id()
            block_key = _store_block_key(algo.blocking_keys(job))
            try:
                self._write(
                    "UPDATE jobs SET job_id_hash=?, canonical_job_id=?, block_key=? WHERE rowid=?",
                    (new_hash, canonical_id, block_key, row["rowid"]),
                )
            except sqlite3.IntegrityError:
                self.norm_conflict_skipped += 1
                continue
            migrated += 1
        if migrated or self.norm_conflict_skipped:
            self._locked_retry(self.conn.commit, rollback_on_error=False)
        return migrated

    def _locked_retry(self, fn, *args, rollback_on_error: bool = True):
        """Run fn, retrying transient SQLITE_BUSY ("locked") failures up to
        _LOCK_RETRIES times with _LOCK_BACKOFF seconds between attempts, then
        re-raise. Any other OperationalError propagates immediately."""
        for attempt in range(_LOCK_RETRIES + 1):
            try:
                return fn(*args)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt >= _LOCK_RETRIES:
                    raise
                if rollback_on_error:
                    try:
                        self.conn.rollback()
                    except sqlite3.Error:
                        pass
                time.sleep(_LOCK_BACKOFF)

    def _write(self, sql: str, params) -> None:
        self._locked_retry(self.conn.execute, sql, params)

    def _maybe_commit(self) -> None:
        """Batch commits: persist after every COMMIT_EVERY write ops."""
        self._pending += 1
        if self._pending >= self.COMMIT_EVERY:
            self.flush()

    def flush(self) -> None:
        """Persist all pending writes and reset the batch counter."""
        if self._pending:
            self._locked_retry(self.conn.commit, rollback_on_error=False)
            self._pending = 0

    def wal_checkpoint(self) -> None:
        """Force the WAL back into the main DB file
        (`PRAGMA wal_checkpoint(TRUNCATE)`). Best effort: a busy checkpoint is
        ignored; close() calls this after flushing."""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass

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
        self._write(
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
        # Text fields are refreshed with COALESCE: a non-empty incoming value
        # overwrites the stored one, an empty/MISSING one leaves it untouched.
        # job_id_hash (the key) and hashes are never rewritten.
        self._write(_UPDATE_SQL, (*_update_params(job, now), job.job_id_hash))

    def upsert(self, job: Job) -> bool:
        """Return True if this job is genuinely new: first time seen and not
        CLOSED, or a previously CLOSED row re-sighted as AUTHENTIC (re-alert).

        Stores all v3 columns; on repeat sight merges seen_sources as before.
        When the re-alert path fires, sets `job.re_alerted = True` (Job is a
        mutable dataclass) so callers can distinguish a recovery alert from a
        first-seen alert; the stored authentic_status is refreshed too.
        """
        return self._locked_retry(self._upsert_flow, job)

    def _upsert_flow(self, job: Job) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT first_seen_at, seen_sources, authentic_status FROM jobs WHERE job_id_hash=?",
            (job.job_id_hash,),
        )
        row = cur.fetchone()
        now = time.time()
        if row is None:
            self._insert(job, now)
            job.first_seen_at = now
            # Only alert on new jobs that are not already closed.
            job.genuinely_new = job.authentic_status != CLOSED
            job.re_alerted = False
            job.seen_sources = [job.source_name]
            self._maybe_commit()
            return job.genuinely_new
        first_seen, seen_sources, stored_status = row
        job.first_seen_at = first_seen
        # CLOSED -> AUTHENTIC recovery: the job re-opened, so alert once more.
        re_alert = stored_status == CLOSED and job.authentic_status == VALID_AUTHENTIC
        job.genuinely_new = re_alert
        job.re_alerted = re_alert
        srcs = (seen_sources or "").split(",")
        if job.source_name and job.source_name not in srcs:
            srcs.append(job.source_name)
        job.seen_sources = [s for s in srcs if s]
        self._update(job, now)
        self._maybe_commit()
        return job.genuinely_new

    def find_candidates(self, job: Job, limit: int | None = None) -> list[sqlite3.Row]:
        """Lookup order: exact job_id_hash -> canonical_job_id -> canonical URL /
        posting_id -> rows matching any block_key (bucketed, LIMIT-bounded).

        The blocking-key LIKE scans (bucketing) ensure candidates are narrowed
        to the incoming job's block_key buckets before fuzzy scoring; the cap
        is CANDIDATE_LIMIT (default 50)."""
        if limit is None:
            limit = self.CANDIDATE_LIMIT
        cur = self.conn.cursor()
        out: list[sqlite3.Row] = []
        seen: set[str] = set()

        def _collect(col: str, value) -> None:
            if not value or col not in _CANDIDATE_COLUMNS:
                return
            col = _CANDIDATE_COLUMNS[col]
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
        best = None            # best hint-bearing candidate (exact/auto_merge/review)
        best_s = 0.0
        score_best = None      # best-scoring candidate overall (identity_score)
        score_best_s = 0.0
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
            if s > score_best_s:
                score_best_s = s
                score_best = ("fuzzy", row, s, hint)
            # A "none" verdict (title-floor failure) must never displace a
            # genuine review/auto_merge match: it carries no linkage hint.
            if hint and s > best_s:
                best_s = s
                best = ("fuzzy", row, s, hint)
        if best is None:
            # Candidates existed but none carried a linkage hint (all verdicts
            # "none" = below the REVIEW bar or a title-floor failure). Preserve
            # the strongest raw similarity as identity evidence when it is
            # strong enough to signal uncertainty: returning 0.0 here would be
            # read by decide() as "no known duplicates" and could AUTO_ACCEPT a
            # near-duplicate. Weak candidates (< MIN_UNCERTAIN_IDENTITY) stay
            # 0.0 so a genuinely-new job is not blocked from the new-job path.
            if score_best is not None and score_best_s >= MIN_UNCERTAIN_IDENTITY:
                result["identity_score"] = score_best[2]
            return result
        via, row, _score, hint = best
        result["identity_score"] = score_best[2] if score_best else 0.0
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
        fields (incl. non-empty title/company/location/role/description/
        date_posted). Never inserts a new row. Canonical ids and hashes are
        left intact (job_id_hash is the key).

        Recovery semantics: when the stored row is CLOSED and the incoming job
        is AUTHENTIC, this is a CLOSED->AUTHENTIC re-alert, so genuinely_new
        and re_alerted are set True (exact-hash re-sightings reach merge, not
        upsert, so this is what fires the advertised re-alert in real runs).
        Any other sighting keeps the current semantics (False/False)."""
        now = time.time()
        job.first_seen_at = existing_row["first_seen_at"]
        recovery = existing_row["authentic_status"] == CLOSED and job.authentic_status == VALID_AUTHENTIC
        job.genuinely_new = recovery
        job.re_alerted = recovery
        srcs = (existing_row["seen_sources"] or "").split(",")
        if job.source_name and job.source_name not in srcs:
            srcs.append(job.source_name)
        job.seen_sources = [s for s in srcs if s]
        self._write(_UPDATE_SQL, (*_update_params(job, now), existing_row["job_id_hash"]))
        self._maybe_commit()

    def close(self):
        self.flush()
        self.wal_checkpoint()
        self.conn.close()
