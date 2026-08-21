from __future__ import annotations

import datetime as dt
import threading
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import algo, secrets
from .dedupe import DedupeStore
from .evidence.negative import negative_signals
from .evidence.positive import positive_signals
from .evidence.reason import compose_reasons
from .evidence.source import SourceStatus, source_authority
from .extractor import extract
from .identity.posting_id import extract_posting_id
from .matcher import matches_profile
from .models import CLOSED, MISSING, Job, RawJob
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
from .verify import verify

# Safety cap: never make more than this many LLM extraction calls per run.
DEFAULT_LLM_BUDGET = 200

# Thread-pool worker counts for each pipeline stage.
FETCH_WORKERS = 4
EXTRACT_WORKERS = 4
VERIFY_WORKERS = 6

# Sort rank: AUTO_ACCEPT > REVIEW > REJECT/"" (plan 1.5.4).
DECISION_RANK = {"AUTO_ACCEPT": 3, "REVIEW": 2, "REJECT": 0, "": 0}


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
) -> dict:
    secrets.load_env(project_root)
    if top_n is not None:
        profile.top_n = top_n
    run_ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    db_path = Path(project_root) / "jobs.db"
    reports_dir = Path(project_root) / "reports"

    adapters = enabled_adapters(profile)
    if source_filter:
        adapters = [a for a in adapters if a.name in source_filter]

    print(f"[jobharness] run {run_ts} | sources: {[a.name for a in adapters]}")
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

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures = {ex.submit(_fetch, a): a for a in adapters}
        for fut in as_completed(futures):
            name, jobs, err, status = fut.result()
            source_statuses[name] = status
            if err:
                errors.append(f"{name}: {err.splitlines()[0]}")
            if not jobs and not err:
                empty.append(name)
            raw_jobs.extend(jobs)
            print(f"[jobharness] {name}: {len(jobs)} raw")

    # Extract + match. LLM extraction is capped to llm_budget jobs; the rest use
    # fast no-LLM extraction to bound API cost. Pre-dedup by title+company (NOT
    # source) so the same posting found via two sources collapses to one LLM
    # extraction and one alert, not two.
    seen_keys = set()
    unique_raws: list[RawJob] = []
    for raw in raw_jobs:
        key = ((raw.title or "").lower(), (raw.company or "").lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_raws.append(raw)

    llm_remaining = llm_budget if use_llm else 0
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
        nonlocal llm_remaining
        with _budget_lock:
            use_this_llm = llm_remaining > 0
            if use_this_llm:
                llm_remaining -= 1
        try:
            job = extract(raw, use_llm=use_this_llm, llm_provider=profile.llm_provider)
        except Exception as e:
            with errors_lock:
                errors.append(f"extract[{raw.source_name}]: {e}")
            return None
        if not job.title or job.title == MISSING:
            return None
        try:
            if not matches_profile(job, profile):
                return None
        except Exception as e:
            with errors_lock:
                errors.append(f"matcher[{job.source_name}]: {e}")
            return None
        return job

    # Extraction is network-bound (LLM calls); parallelize within the budget.
    with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as ex:
        futures = {ex.submit(_extract_one, raw): raw for raw in unique_raws}
        for fut in as_completed(futures):
            job = fut.result()
            if job is not None:
                matched.append(job)
    if use_llm and llm_remaining == 0:
        print(f"[jobharness] LLM budget ({llm_budget}) reached; remaining extractions used raw fields")
    print(f"[jobharness] matched after filter: {len(matched)}")

    # Verify concurrently (network-bound). Verify also sets confidence_score.
    if verify_reachable and matched:
        with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as ex:
            futs = {ex.submit(verify, job, True): job for job in matched}
            for fut in as_completed(futs):
                job = futs[fut]
                try:
                    fut.result()
                except Exception as e:
                    errors.append(f"verify[{job.source_name}]: {e}")
                    job.missing_fields.append("verified_reachable")
    else:
        for job in matched:
            verify(job, check_reachable=False)

    # Identity + evidence enrichment: canonical URLs, posting ID, source
    # authority, canonical job id, block keys, fingerprint, evidence/reasons.
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
    store = DedupeStore(db_path)
    try:
        for job in matched:
            try:
                fl = store.fuzzy_lookup(job)
                job.identity_score = fl["identity_score"]
                job.match_score = score_match(job, profile)
                state = STATE_CLOSED if job.authentic_status == CLOSED else (
                    STATE_INVALID_URL
                    if not job.apply_url_direct or job.apply_url_direct == MISSING
                    else STATE_OPEN
                )
                job.decision, decision_reasons = decide(
                    job.identity_score, job.authenticity_score, job.match_score, state
                )
                job.reason = list(job.reason) + decision_reasons
                if fl["matched"]:
                    store.merge(job, fl["existing_row"])
                    job.matched_via = fl["matched_via"]
                    job.possible_duplicate_of = fl["possible_duplicate_of"]
                else:
                    if fl["decision_hint"] == "REVIEW":
                        job.possible_duplicate_of = fl["possible_duplicate_of"]
                        job.matched_via = fl["matched_via"] or "exact"
                    store.upsert(job)
            except Exception as e:
                errors.append(f"dedupe: {e}\n{traceback.format_exc()}")
    finally:
        store.close()

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
    rep = write_reports(matched, reports_dir, run_ts=run_ts)

    # Structured PDF of the report (best-effort; falls back to CSV silently).
    if rep["total"]:
        rep["pdf"] = write_pdf(rep["html"], f"{rep['dir']}/report.pdf")

    # Telegram push (genuinely new + authentic + sufficient confidence only)
    pushed = 0
    if push_telegram and telegram.configured():
        try:
            pushed = telegram.notify_new(matched)
            attachment = rep.get("pdf") or rep["csv"]
            telegram.send_file(attachment, caption=f"Job harness run {run_ts}: {rep['new_count']} new")
        except Exception as e:
            errors.append(f"telegram: {e}")
    elif push_telegram and not telegram.configured():
        print("[jobharness] Telegram not configured (TELEGRAM_BOT_TOKEN/CHAT_ID) - skipping push")

    decisions = {k: v for k, v in Counter(j.decision or "NONE" for j in matched).items() if v}
    print(
        f"[jobharness] done: match={rep['total']} new={rep['new_count']} closed={rep['closed_count']} "
        f"pushed={pushed} empty={empty} errors={len(errors)}"
    )
    print(f"[jobharness] decisions: {decisions}")
    print(
        "[jobharness] source statuses: "
        + ", ".join(f"{n}={s.value}" for n, s in source_statuses.items())
    )
    print(f"[jobharness] reports: {rep['html']}")

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
