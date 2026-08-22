"""SQLite-backed reachability cache for the verify stage.

Every run without a cache re-fetches each apply URL (LinkedIn in particular
answers with hundreds of 429s) and re-marks the same jobs DEGRADED each run.
This module stores definitive outcomes keyed by apply URL:

- reachable (2xx/3xx, non-blocked, non-closed)  -> cached OK_TTL_S
- CLOSED (404/410 / closed marker)               -> cached CLOSED_TTL_S

Transient outcomes (429/5xx/network -> DEGRADED) are NEVER cached: the next
run must retry them.

The store lives in the project's ``jobs.db`` (same file as dedupe) in a
``verify_cache`` table. It is thread-safe (a single connection guarded by a
process lock) and best-effort: any cache failure is swallowed so verification
itself never breaks because of the cache.

``configure(db_path)`` is called once by the runner before the verify stage.
``reset_for_test``/module-level state make it trivially testable.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from .logging import get_logger

logger = get_logger("verify_cache")

# A reachable URL stays "known good" for a day; closed markers are stable for
# longer because a removed posting does not come back (and even if it did, the
# dedupe CLOSED->AUTHENTIC re-alert path handles recovery).
OK_TTL_S = 24 * 3600
CLOSED_TTL_S = 7 * 24 * 3600

_conn: sqlite3.Connection | None = None
_path: str | None = None
_lock = threading.Lock()

_CREATE = (
    "CREATE TABLE IF NOT EXISTS verify_cache ("
    "  url TEXT PRIMARY KEY,"
    "  status TEXT NOT NULL,"          # 'ok' | 'closed'
    "  status_code INTEGER,"
    "  checked_at REAL NOT NULL,"
    "  redirect_to TEXT"
    ")"
)
_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS ix_verify_cache_checked ON verify_cache(checked_at)"


def configure(db_path: str | Path | None) -> None:
    """Open (or reopen) the cache on ``db_path``. Idempotent: re-configuring
    with the same path is a no-op. Passing None disables the cache.

    Thread-safe: the connection is shared across the verify worker pool via a
    process lock (sqlite3 default connections are not thread-safe).
    """
    global _conn, _path
    p = str(db_path) if db_path else None
    with _lock:
        if p == _path and _conn is not None:
            return
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
        _path = p
        if p is None:
            return
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p, check_same_thread=False, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE)
        conn.execute(_CREATE_INDEX)
        conn.commit()
        _conn = conn


def _ensure() -> sqlite3.Connection | None:
    if _conn is None:
        return None
    return _conn


def lookup(url: str) -> dict | None:
    """Return a cached verify outcome for ``url`` or None (cache miss / stale
    / disabled). ``url`` is the canonical apply URL the runner uses as cache
    key. A hit returns the recorded ctx fields (status_code/redirect_to) so the
    caller can rebuild the verify context without re-fetching."""
    if not url:
        return None
    conn = _ensure()
    if conn is None:
        return None
    now = time.time()
    try:
        with _lock:
            row = conn.execute(
                "SELECT status, status_code, checked_at, redirect_to FROM verify_cache WHERE url=?",
                (url,),
            ).fetchone()
    except sqlite3.Error as e:
        logger.debug("verify_cache lookup failed for %s: %s", url, e)
        return None
    if not row:
        return None
    status, status_code, checked_at, redirect_to = row
    ttl = OK_TTL_S if status == "ok" else CLOSED_TTL_S
    if now - float(checked_at or 0) > ttl:
        return None  # stale -> caller re-verifies
    return {
        "status": status,
        "status_code": status_code,
        "redirect_to": redirect_to or "",
        "checked_at": float(checked_at or 0),
    }


def record(url: str, status: str, status_code: int | None = None, redirect_to: str = "") -> None:
    """Persist a DEFINITIVE outcome. ``status`` must be 'ok' or 'closed';
    transient (DEGRADED) results are intentionally not cached."""
    if not url or status not in ("ok", "closed"):
        return
    conn = _ensure()
    if conn is None:
        return
    now = time.time()
    try:
        with _lock:
            conn.execute(
                "INSERT INTO verify_cache(url, status, status_code, checked_at, redirect_to) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(url) DO UPDATE SET "
                "status=excluded.status, status_code=excluded.status_code, "
                "checked_at=excluded.checked_at, redirect_to=excluded.redirect_to",
                (url, status, status_code, now, redirect_to or ""),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.debug("verify_cache record failed for %s: %s", url, e)


def close() -> None:
    global _conn, _path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
        _path = None
