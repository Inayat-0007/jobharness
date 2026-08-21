from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
import time
import traceback
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TypeVar

from . import algo, secrets
from .dedupe import DedupeStore
from .evidence.negative import negative_signals
from .evidence.positive import positive_signals
from .evidence.reason import compose_reasons
from .evidence.source import SourceStatus, source_authority
from .extractor import extract
from .identity.company import company_identity
from .identity.location import location_bucket
from .identity.posting_id import extract_posting_id
from .identity.title import normalize_title
from .logging import get_logger
from .matcher import matches_profile
from .models import CLOSED, MISSING, Job, RawJob, _parse_date
from .notify import telegram
from .profile import Profile
from .registry import enabled_adapters
from .report import write_pdf, write_reports
from .scoring.authenticity import authenticity_score as _authenticity_score
from .scoring.decision import decide
from .scoring.matching import score_match
from .scoring.thresholds import STATE_CLOSED, STATE_INVALID_URL, STATE_OPEN
from .sources.exceptions import (
    AuthRequiredError,
    BlockedError,
    ParseFailureError,
    RateLimitedError,
    SourceDownError,
)
from .urlutil import canonicalize_url
from .verify import DEGRADED, verify

# Optional LLM call observability: stats() is added to llm.provider by a
# parallel change; import defensively so older providers still work.
_llm_stats: Callable[[], dict[str, dict[str, int]]] | None
try:
    from .llm.provider import stats as _llm_stats
except (ImportError, AttributeError):  # pragma: no cover - provider without stats
    _llm_stats = None

# Safety cap: never make more than this many LLM extraction calls per run.
DEFAULT_LLM_BUDGET = 200

# Thread-pool worker counts for each pipeline stage.
FETCH_WORKERS = 4
EXTRACT_WORKERS = 4
VERIFY_WORKERS = 6
DEDUPE_WORKERS = 4

# In-run fuzzy linkage cap: run_seen rows are compared against every unmatched
# job in the same run, so once the tracked set exceeds this many entries the
# scan is skipped to avoid an O(n^2) blowup. Typical runs have <50 matched
# jobs, so the scan is normally full coverage.
_RUN_SEEN_CAP = 200

# Sort rank: AUTO_ACCEPT > REVIEW > REJECT/"" (plan 1.5.4).
DECISION_RANK = {"AUTO_ACCEPT": 3, "REVIEW": 2, "REJECT": 0, "": 0}

logger = get_logger("runner")


def _pre_dedup_key(raw) -> tuple[str, str, str]:
    """Cross-source pre-dedup key: (normalized title, canonical company,
    location bucket).

    The same posting found via two sources in the same city collapses to one
    extraction/alert; two postings with the same title+company in different
    cities survive pre-dedup because the location bucket is part of the key.
    """
    title = normalize_title(getattr(raw, "title", "") or "")
    company = company_identity(raw)[0]
    loc = location_bucket(getattr(raw, "location", "") or "")
    return title, company, loc


_T = TypeVar("_T")
_R = TypeVar("_R")


def _bounded_map(
    executor,
    items: Sequence[_T],
    fn: Callable[[_T], _R],
    window,
    deadline_passed,
    on_deadline,
    on_item_error=None,
) -> list[tuple[int, _R | None]]:
    """Run fn over items in bounded windows: at most `window` futures in
    flight at once (windows of `window` items). The timeout deadline is
    checked before each window so a runaway stage stops submitting new work.

    Returns [(index, result), ...] in completion order, where index is the
    item's position in `items`. Per-item exceptions are captured: when a
    future raises, on_item_error(index, exc) is invoked from inside the
    except block (so traceback.format_exc() sees the real traceback) and
    (index, None) is returned for that item. on_deadline(i) is invoked with
    the first unsubmitted window start when the deadline passes, then the
    loop stops; i is the count of items already submitted.
    """
    results: list[tuple[int, _R | None]] = []
    for i in range(0, len(items), window):
        if deadline_passed():
            on_deadline(i)
            break
        futs = {
            executor.submit(fn, item): (i + k, item)
            for k, item in enumerate(items[i : i + window])
        }
        for fut in as_completed(futs):
            idx, _item = futs[fut]
            try:
                results.append((idx, fut.result()))
            except Exception as exc:
                if on_item_error is not None:
                    on_item_error(idx, exc)
                results.append((idx, None))
    return results


def _run_seen_match(job, run_seen):
    """Best in-run fuzzy match for a job whose committed-state lookup found
    nothing, mirroring DedupeStore.fuzzy_lookup: an identical job_id_hash or
    canonical_job_id is an auto_merge; otherwise the job is scored against
    every tracked row with algo.composite_similarity and the best non-"none"
    verdict wins.

    Returns (verdict, sqlite3.Row, score) or None. Iteration is in insertion
    order so results are deterministic. The scan is skipped entirely once
    run_seen exceeds _RUN_SEEN_CAP entries.
    """
    if not run_seen or len(run_seen) > _RUN_SEEN_CAP:
        return None
    best = None
    for h, row in run_seen.items():
        if job.job_id_hash and h == job.job_id_hash:
            return ("auto_merge", row, 1.0)
        if row["canonical_job_id"] and row["canonical_job_id"] == job.canonical_job_id:
            return ("auto_merge", row, 1.0)
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
        if verdict != "none" and (best is None or s > best[2]):
            best = (verdict, row, s)
    return best


def run_once(
    profile: Profile,
    project_root: str,
    *,
    source_filter: list[str] | None = None,
    top_n: int | None = None,
    verify_reachable: bool = True,
    use_llm: bool = True,
    push_telegram: bool = True,
    llm_budget: int = DEFAULT_LLM_BUDGET,
    since_days: int | None = None,
) -> dict:
    start_mono = time.monotonic()
    run_started_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    secrets.load_env(Path(project_root))
    if top_n is not None:
        profile.top_n = top_n
    run_ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    db_path = Path(project_root) / "jobs.db"
    reports_dir = Path(project_root) / "reports"

    # Run timeout budget (Profile.timeout_minutes; <= 0 = no limit). Once the
    # deadline passes, remaining pipeline stages are skipped best-effort
    # (in-flight work is never killed, just no new work is submitted), and the
    # run still writes partial reports + the manifest, so it never hangs
    # beyond the budget and never crashes.
    timeout_minutes = max(0, int(profile.timeout_minutes or 0))
    deadline = start_mono + timeout_minutes * 60 if timeout_minutes > 0 else None
    timed_out = False
    timeout_aborted: dict[str, bool] = {
        "extract": False,
        "verify": False,
        "dedupe": False,
        "push": False,
    }
    stage_elapsed: dict[str, float] = {}

    def _deadline_passed() -> bool:
        nonlocal timed_out
        if deadline is None or time.monotonic() < deadline:
            return False
        if not timed_out:
            timed_out = True
            logger.warning(
                "run timeout budget (%d min) exceeded; aborting remaining work",
                timeout_minutes,
            )
        return True

    adapters = enabled_adapters(profile)
    if source_filter:
        adapters = [a for a in adapters if a.name in source_filter]

    logger.info("run %s | sources: %s", run_ts, [a.name for a in adapters])
    raw_jobs: list[RawJob] = []
    empty: list[str] = []
    errors: list[str] = []
    errors_lock = threading.Lock()
    source_statuses: dict[str, SourceStatus] = {}

    def _fetch(adapter):
        try:
            jobs = adapter.fetch(profile)
            return adapter.name, jobs, None, SourceStatus.OK if jobs else SourceStatus.EMPTY
        except RateLimitedError as e:
            return adapter.name, [], f"{e}", SourceStatus.RATE_LIMITED
        except AuthRequiredError as e:
            return adapter.name, [], f"{e}", SourceStatus.AUTH_REQUIRED
        except SourceDownError as e:
            return adapter.name, [], f"{e}", SourceStatus.SOURCE_DOWN
        except ParseFailureError as e:
            return adapter.name, [], f"{e}", SourceStatus.PARSE_FAILURE
        except BlockedError as e:
            return adapter.name, [], f"{e}", SourceStatus.BLOCKED
        except Exception as e:
            return adapter.name, [], f"{e}\n{traceback.format_exc()}", SourceStatus.SOURCE_DOWN

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures = {ex.submit(_fetch, a): a for a in adapters}
        for fut in as_completed(futures):
            name, jobs, err, status = fut.result()
            source_statuses[name] = status
            if err:
                first = err.splitlines()[0]
                errors.append(f"{name}: {first}")
                logger.error("%s: %s", name, first)
            if not jobs and not err:
                empty.append(name)
            raw_jobs.extend(jobs)
            logger.info("%s: %d raw", name, len(jobs))
    stage_elapsed["fetch"] = time.monotonic() - t0

    # Extract + match. LLM extraction is capped to llm_budget jobs; the rest use
    # fast no-LLM extraction to bound API cost. Pre-dedup by normalized
    # title+company+location bucket (NOT source) so the same posting found via
    # two sources in the same city collapses to one LLM extraction and one
    # alert, while same title+company in different cities survive.
    seen_keys = set()
    collapsed_keys = set()
    unique_raws: list[RawJob] = []
    for raw in raw_jobs:
        key = _pre_dedup_key(raw)
        if key in seen_keys:
            # Count each collapsing key once (a single-key group of size >1
            # counts as one dropped key, regardless of group size).
            collapsed_keys.add(key)
            continue
        seen_keys.add(key)
        unique_raws.append(raw)
    if collapsed_keys:
        logger.info(
            "pre-dedup: dropped %d collapsed key(s) "
            "(same title+company+location from multiple sources)",
            len(collapsed_keys),
        )

    # Incremental mode: --since N days drops jobs whose posted_date is older.
    # Unparseable dates are kept (cannot prove staleness; default behavior).
    if since_days is not None and since_days > 0:
        cutoff = time.time() - since_days * 86400
        kept = []
        for raw in unique_raws:
            parsed = _parse_date(raw.posted_date)
            if parsed is None or parsed.timestamp() >= cutoff:
                kept.append(raw)
        if len(kept) != len(unique_raws):
            logger.info("--since %dd kept %d/%d raw jobs", since_days, len(kept), len(unique_raws))
        unique_raws = kept

    llm_remaining = llm_budget if use_llm else 0
    llm_used = 0
    matched: list[Job] = []
    _budget_lock = threading.Lock()

    # Prioritize jobs whose title/company already hints at a profile match so
    # the capped LLM budget is spent on likely matches first.
    def _likely(raw: RawJob) -> bool:
        t = f"{raw.title or ''} {raw.company or ''}".lower()
        return any(term.lower() in t for term in profile.roles) or any(
            kw.lower() in t for kw in profile.keywords
        )

    unique_raws.sort(key=_likely, reverse=True)

    def _extract_one(raw) -> Job | None:
        nonlocal llm_remaining, llm_used
        with _budget_lock:
            use_this_llm = llm_remaining > 0
            if use_this_llm:
                llm_remaining -= 1
                llm_used += 1
        try:
            job = extract(raw, use_llm=use_this_llm, llm_provider=profile.llm_provider)
        except Exception as e:
            with errors_lock:
                msg = f"extract[{raw.source_name}]: {e}"
                errors.append(msg)
                logger.error("%s", msg)
            return None
        if not job.title or job.title == MISSING:
            logger.info(
                "extraction dropped empty-title job (source=%s, company=%s)",
                raw.source_name,
                raw.company or "",
            )
            return None
        try:
            if not matches_profile(job, profile):
                return None
        except Exception as e:
            with errors_lock:
                msg = f"matcher[{job.source_name}]: {e}"
                errors.append(msg)
                logger.error("%s", msg)
            return None
        return job

    # Extraction is network-bound (LLM calls); parallelize within the budget.
    # Bounded futures: at most EXTRACT_WORKERS futures in flight at once
    # (windows of EXTRACT_WORKERS jobs). The timeout deadline is checked before
    # each window so a runaway stage stops submitting new work.
    def _abort_extract(i):
        timeout_aborted["extract"] = True
        logger.warning(
            "run timeout exceeded: aborting extract stage (submitted %d/%d raw jobs)",
            i,
            len(unique_raws),
        )

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as ex:
        for _, job in _bounded_map(
            ex, unique_raws, _extract_one, EXTRACT_WORKERS, _deadline_passed, _abort_extract
        ):
            if job is not None:
                matched.append(job)
    stage_elapsed["extract"] = time.monotonic() - t0
    if use_llm and llm_remaining == 0:
        logger.info("LLM budget (%d) reached; remaining extractions used raw fields", llm_budget)
    logger.info("matched after filter: %d", len(matched))

    # Verify concurrently (network-bound). Verify also sets confidence_score.
    # Bounded futures: at most VERIFY_WORKERS futures in flight at once.
    def _abort_verify(i):
        timeout_aborted["verify"] = True
        logger.warning(
            "run timeout exceeded: aborting verify stage (submitted %d/%d jobs)",
            i,
            len(matched),
        )

    def _on_verify_error(idx, exc):
        v_job = matched[idx]
        msg = f"verify[{v_job.source_name}]: {exc}"
        errors.append(msg)
        logger.error("%s", msg)
        v_job.missing_fields.append("verified_reachable")

    t0 = time.monotonic()
    if verify_reachable and matched:
        with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as ex:
            _bounded_map(
                ex,
                matched,
                lambda v_job: verify(v_job, True),
                VERIFY_WORKERS,
                _deadline_passed,
                _abort_verify,
                _on_verify_error,
            )
    else:
        for job in matched:
            verify(job, check_reachable=False)
    stage_elapsed["verify"] = time.monotonic() - t0

    # Identity + evidence enrichment: canonical URLs, posting ID, source
    # authority, canonical job id, block keys, fingerprint, evidence/reasons.
    t0 = time.monotonic()
    for job in matched:
        job.original_url = job.apply_url_direct
        job.canonical_url = canonicalize_url(job.apply_url_direct)
        job.final_url = job.apply_url_direct
        job.posting_id = extract_posting_id(job)
        job.source_authority = source_authority(job.source_name)
        job.canonical_job_id = job.compute_canonical_id()
        job.block_key = algo.blocking_keys(job)
        job.compute_fingerprint()
        job.authenticity_score = float(_authenticity_score(job))
        vctx = getattr(job, "_verify_ctx", None)
        job.evidence = positive_signals(job, vctx)
        job.negative_evidence = negative_signals(job, vctx)
        job.reason = compose_reasons(job.evidence, job.negative_evidence)
    stage_elapsed["enrich"] = time.monotonic() - t0

    # Sources that fetched jobs but none matched the profile.
    matched_by_source = Counter(j.source_name for j in matched)
    for a in adapters:
        if source_statuses.get(a.name) == SourceStatus.OK and matched_by_source.get(a.name, 0) == 0:
            source_statuses[a.name] = SourceStatus.NO_MATCH

    # De-duplicate + mark genuinely new. CLOSED jobs are still stored (so we
    # don't re-alert on them) but never counted as genuinely_new for alerts.
    # Cross-run fuzzy linkage runs BEFORE upsert: HIGH matches are merged into
    # the stored row (no new row, no alert), MEDIUM gets possible_duplicate_of
    # + REVIEW decision, LOW follows the normal new path.
    #
    # Parallel lookup phase: fuzzy_lookup (candidate scan + composite
    # similarity) is read-only and expensive, so it runs on DEDUPE_WORKERS
    # threads. The store's SQLite connection is not thread-safe
    # (check_same_thread default), so each worker opens its own read-only
    # DedupeStore (max_age_days=0 disables pruning, reports_dir=None disables
    # the description backfill). Results are gathered in input order. Writes
    # stay on the single main store and run SEQUENTIALLY afterwards (batched
    # commits inside the store still apply).
    t0 = time.monotonic()
    re_alerted_count = 0
    store = DedupeStore(db_path, reports_dir=reports_dir)
    try:
        if _deadline_passed():
            timeout_aborted["dedupe"] = True
            logger.warning("run timeout exceeded: skipping dedupe stage")
        else:
            lookups: list[tuple[int, Job, dict | None]] = []
            _tls = threading.local()

            def _init_worker_store() -> None:
                _tls.store = DedupeStore(db_path, max_age_days=0, reports_dir=None)

            def _lookup(job) -> dict:
                return _tls.store.fuzzy_lookup(job)

            def _abort_dedupe_lookups(i):
                timeout_aborted["dedupe"] = True
                logger.warning(
                    "run timeout exceeded: aborting dedupe lookups (submitted %d/%d jobs)",
                    i,
                    len(matched),
                )

            def _on_lookup_error(_idx, exc):
                msg = f"dedupe: {exc}\n{traceback.format_exc()}"
                errors.append(msg)
                logger.error("dedupe: %s", exc, exc_info=True)

            try:
                with ThreadPoolExecutor(
                    max_workers=DEDUPE_WORKERS, initializer=_init_worker_store
                ) as ex:
                    for idx, d_fl in _bounded_map(
                        ex,
                        matched,
                        _lookup,
                        DEDUPE_WORKERS,
                        _deadline_passed,
                        _abort_dedupe_lookups,
                        _on_lookup_error,
                    ):
                        lookups.append((idx, matched[idx], d_fl))
            except Exception as e:
                msg = f"dedupe: {e}\n{traceback.format_exc()}"
                errors.append(msg)
                logger.error("dedupe: %s", e, exc_info=True)

            # Upsert phase: sequential, in input order (single SQLite writer;
            # fuzzy results are re-associated to the original position).
            lookups.sort(key=lambda t: t[0])
            # In-run fuzzy linkage: the parallel lookups above ran against
            # committed state before ANY upsert, so a second source's sighting
            # of the same job (title variant -> different job_id_hash) in the
            # SAME run would miss and store a duplicate row + duplicate alert.
            # Track every row this run stores and fuzzy-check unmatched jobs
            # against them first, mirroring DedupeStore.fuzzy_lookup verdicts
            # (auto_merge -> merge, review -> flag possible_duplicate_of but
            # still store). Capped by _RUN_SEEN_CAP so the scan cannot blow up
            # to O(n^2); insertion order keeps the scan deterministic.
            run_seen: dict[str, sqlite3.Row] = {}
            for _, d_job, d_fl in lookups:
                if d_fl is None:
                    continue
                try:
                    run_match = None if d_fl["matched"] else _run_seen_match(d_job, run_seen)
                    if run_match is not None:
                        run_verdict, run_row, run_score = run_match
                    else:
                        run_verdict, run_row, run_score = None, None, 0.0
                    d_job.identity_score = run_score if run_match is not None else d_fl["identity_score"]
                    d_job.match_score = score_match(d_job, profile)
                    state = STATE_CLOSED if d_job.authentic_status == CLOSED else (
                        STATE_INVALID_URL
                        if not d_job.apply_url_direct or d_job.apply_url_direct == MISSING
                        else STATE_OPEN
                    )
                    d_job.decision, decision_reasons = decide(
                        d_job.identity_score, d_job.authenticity_score, d_job.match_score, state
                    )
                    d_job.reason = list(d_job.reason) + decision_reasons
                    if d_fl["matched"]:
                        store.merge(d_job, d_fl["existing_row"])
                        d_job.matched_via = d_fl["matched_via"]
                        d_job.possible_duplicate_of = d_fl["possible_duplicate_of"]
                    elif run_verdict == "auto_merge":
                        # In-run auto_merge: fold into the row stored by an
                        # earlier job in this run instead of inserting a
                        # duplicate row. re_alerted is left to dedupe.merge
                        # (CLOSED->AUTHENTIC recovery semantics live there).
                        store.merge(d_job, run_row)
                        d_job.matched_via = "run_fuzzy"
                        d_job.possible_duplicate_of = run_row["job_id_hash"]
                    else:
                        if d_fl["decision_hint"] == "REVIEW":
                            d_job.possible_duplicate_of = d_fl["possible_duplicate_of"]
                            d_job.matched_via = d_fl["matched_via"] or "exact"
                        if run_verdict == "review":
                            d_job.possible_duplicate_of = run_row["job_id_hash"]
                            d_job.matched_via = "run_fuzzy"
                        store.upsert(d_job)
                        run_row = store.conn.execute(
                            "SELECT * FROM jobs WHERE job_id_hash=?", (d_job.job_id_hash,)
                        ).fetchone()
                        if run_row is not None:
                            run_seen[d_job.job_id_hash] = run_row
                    if d_job.re_alerted:
                        re_alerted_count += 1
                        logger.info(
                            "re-alerted (previously CLOSED): %s | %s", d_job.company, d_job.title
                        )
                except Exception as e:
                    msg = f"dedupe: {e}\n{traceback.format_exc()}"
                    errors.append(msg)
                    logger.error("dedupe: %s", e, exc_info=True)
            if re_alerted_count:
                logger.info("re-alerted count: %d", re_alerted_count)
    finally:
        store.close()
    stage_elapsed["dedupe"] = time.monotonic() - t0

    # Rank by decision, then match_score (fallback: confidence_score until
    # Phase 3), then freshness, then newest first_seen.
    matched.sort(
        key=lambda j: (
            DECISION_RANK.get(j.decision, 0),
            j.match_score if j.match_score else j.confidence_score,
            j.freshness == "fresh",
            -j.first_seen_at,
        ),
        reverse=True,
    )

    # Report
    t0 = time.monotonic()
    rep = write_reports(matched, reports_dir, run_ts=run_ts)

    # Structured PDF of the report (best-effort; falls back to CSV silently).
    if rep["total"]:
        rep["pdf"] = write_pdf(str(rep["html"]), f"{rep['dir']}/report.pdf")
    stage_elapsed["report"] = time.monotonic() - t0

    # Telegram push (genuinely new + not-CLOSED + accepted decision).
    # DEGRADED jobs (verification could not confirm reachability - e.g. the
    # source rate-limited the verify check while the listing fetch itself
    # succeeded, so the job is genuinely real) ARE pushed: the card carries a
    # visible "link could not be verified" warning (telegram._card_text)
    # instead of the job being silently withheld. CLOSED jobs remain
    # excluded. All pushed jobs still count in new_count, so manifest and
    # reports stay consistent with the jobs that were actually stored.
    t0 = time.monotonic()
    pushed = 0
    if push_telegram and _deadline_passed():
        timeout_aborted["push"] = True
        logger.warning("run timeout exceeded: skipping telegram push")
    elif push_telegram and telegram.configured():
        try:
            push_jobs = [
                j
                for j in matched
                if j.genuinely_new
                and j.authentic_status != CLOSED
                and j.decision not in ("", "REJECT")
            ]
            degraded_pushed = sum(1 for j in push_jobs if j.authentic_status == DEGRADED)
            if degraded_pushed:
                logger.info(
                    "pushing %d DEGRADED job(s) with unverified-link warning "
                    "(listing fetch succeeded; verify rate-limited)",
                    degraded_pushed,
                )
            pushed = telegram.notify_new(push_jobs)
            attachment = str(rep.get("pdf") or rep["csv"])
            telegram.send_file(attachment, caption=f"Job harness run {run_ts}: {rep['new_count']} new")
        except Exception as e:
            msg = f"telegram: {e}"
            errors.append(msg)
            logger.error("%s", msg)
    elif push_telegram and not telegram.configured():
        logger.warning("Telegram not configured (TELEGRAM_BOT_TOKEN/CHAT_ID) - skipping push")
    stage_elapsed["push"] = time.monotonic() - t0

    # Run manifest: written into the same timestamp dir as the report
    # (rep["dir"]), after the push stage so push timing is included.
    manifest = {
        "run_ts": run_ts,
        "run_started": run_started_iso,
        "run_finished": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "wall_clock_seconds": round(time.monotonic() - start_mono, 3),
        "stages": {k: round(v, 3) for k, v in stage_elapsed.items()},
        "sources": {name: status.value for name, status in source_statuses.items()},
        "raw_job_count": len(raw_jobs),
        "matched_count": len(matched),
        "new_count": rep["new_count"],
        "re_alerted_count": re_alerted_count,
        "errors": len(errors),
        "llm_budget_used": llm_used,
        "llm_budget": llm_budget,
        "timeout": timed_out,
        "timeout_aborted_stages": [k for k, v in timeout_aborted.items() if v],
    }
    try:
        manifest_dir = Path(str(rep["dir"]))
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    except OSError as e:
        msg = f"manifest: {e}"
        errors.append(msg)
        logger.error("%s", msg)

    decisions = {k: v for k, v in Counter(j.decision or "NONE" for j in matched).items() if v}
    logger.info(
        "done: match=%d new=%d closed=%d pushed=%d empty=%s errors=%d",
        rep["total"],
        rep["new_count"],
        rep["closed_count"],
        pushed,
        empty,
        len(errors),
    )
    logger.info("decisions: %s", decisions)
    if _llm_stats is not None:
        try:
            _s = _llm_stats() or {}
            logger.info(
                "LLM usage: %s calls, %s ok, %s rate-limited",
                _s.get("attempts", 0),
                _s.get("good", 0),
                _s.get("rate_limited", 0),
            )
        except Exception:  # pragma: no cover - best-effort observability only
            pass
    logger.info(
        "source statuses: %s",
        ", ".join(f"{n}={s.value}" for n, s in source_statuses.items()),
    )
    logger.info("reports: %s", rep["html"])
    if timed_out:
        logger.warning("run timed out; aborted stages: %s", timeout_aborted)

    return {
        "run_ts": run_ts,
        "report": rep,
        "empty": empty,
        "errors": errors,
        "pushed": pushed,
        "total_raw": len(raw_jobs),
        "total_matched": len(matched),
        "source_statuses": {k: v.value for k, v in source_statuses.items()},
    }
