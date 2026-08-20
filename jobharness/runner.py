from __future__ import annotations

import datetime as dt
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import secrets
from .models import Job, RawJob, MISSING
from .profile import Profile
from .registry import enabled_adapters
from .extractor import extract
from .matcher import matches_profile
from .verify import verify
from .dedupe import DedupeStore
from .report import write_reports
from .notify import telegram


def run_once(
    profile: Profile,
    project_root: str,
    *,
    source_filter: list[str] | None = None,
    top_n: int | None = None,
    verify_reachable: bool = True,
    use_llm: bool = True,
    push_telegram: bool = True,
) -> dict:
    secrets.load_env(project_root)
    if top_n:
        profile.top_n = top_n
    run_ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    db_path = f"{project_root}/jobs.db"
    reports_dir = f"{project_root}/reports"

    adapters = enabled_adapters(profile)
    if source_filter:
        adapters = [a for a in adapters if a.name in source_filter]

    print(f"[jobharness] run {run_ts} | sources: {[a.name for a in adapters]}")
    raw_jobs: list[RawJob] = []
    blocked: list[str] = []
    errors: list[str] = []

    def _fetch(adapter):
        try:
            return adapter.name, adapter.fetch(profile), None
        except Exception as e:
            return adapter.name, [], f"{e}\n{traceback.format_exc()}"

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_fetch, a): a for a in adapters}
        for fut in as_completed(futures):
            name, jobs, err = fut.result()
            if err:
                errors.append(f"{name}: {err.splitlines()[0]}")
            if not jobs and not err:
                blocked.append(name)
            raw_jobs.extend(jobs)
            print(f"[jobharness] {name}: {len(jobs)} raw")

    # Extract + match
    matched: list[Job] = []
    for raw in raw_jobs:
        try:
            job = extract(raw, use_llm=use_llm, llm_provider=profile.llm_provider)
        except Exception as e:
            errors.append(f"extract[{raw.source_name}]: {e}")
            continue
        if not job.title or job.title == MISSING:
            continue
        try:
            if not matches_profile(job, profile):
                continue
        except Exception:
            pass
        matched.append(job)
    print(f"[jobharness] matched after filter: {len(matched)}")

    # Verify (resolve apply URL, detect CLOSED)
    for job in matched:
        try:
            verify(job, check_reachable=verify_reachable)
        except Exception as e:
            errors.append(f"verify[{job.source_name}]: {e}")
            job.missing_fields.append("verified_reachable")

    # De-duplicate + mark genuinely new
    store = DedupeStore(db_path)
    try:
        for job in matched:
            try:
                store.upsert(job)
            except Exception as e:
                errors.append(f"dedupe: {e}")
    finally:
        store.close()

    # Report
    rep = write_reports(matched, reports_dir, run_ts=run_ts)

    # Telegram push (genuinely new + authentic only)
    pushed = 0
    if push_telegram and telegram.configured():
        try:
            pushed = telegram.notify_new(matched)
            csv_path = rep["csv"]
            telegram.send_file(csv_path, caption=f"Job harness run {run_ts}: {rep['new_count']} new")
        except Exception as e:
            errors.append(f"telegram: {e}")
    elif push_telegram and not telegram.configured():
        print("[jobharness] Telegram not configured (TELEGRAM_BOT_TOKEN/CHAT_ID) - skipping push")

    print(
        f"[jobharness] done: match={rep['total']} new={rep['new_count']} closed={rep['closed_count']} "
        f"pushed={pushed} blocked={blocked} errors={len(errors)}"
    )
    print(f"[jobharness] reports: {rep['html']}")

    return {
        "run_ts": run_ts,
        "report": rep,
        "blocked": blocked,
        "errors": errors,
        "pushed": pushed,
        "total_raw": len(raw_jobs),
        "total_matched": len(matched),
    }
