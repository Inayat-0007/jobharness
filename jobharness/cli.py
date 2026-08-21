from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from . import secrets
from .dashboard import build_dashboard
from .logging import get_logger, setup_logging
from .profile import load_profile, make_demo_profile
from .registry import all_adapters
from .runner import DEFAULT_LLM_BUDGET, run_once

PROJECT_ROOT = Path(__file__).resolve().parent.parent

log = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobharness", description="On-demand job harvest harness.")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Run one harvest pass.")
    r.add_argument("--profile", default=str(PROJECT_ROOT / "profiles" / "demo.yaml"))
    r.add_argument("--source", action="append", dest="sources", help="Only run these source names (repeatable).")
    r.add_argument("--top", type=int, default=None)
    r.add_argument("--llm-budget", type=int, default=None, help="Cap LLM extraction calls per run (default 200).")
    r.add_argument("--no-llm", action="store_true", help="Skip LLM extraction (use raw fields only).")
    r.add_argument("--no-verify", action="store_true", help="Skip apply-URL reachability check.")
    r.add_argument("--no-push", action="store_true", help="Skip Telegram push.")
    r.add_argument("--dry-run", action="store_true", help="Alias for --no-verify --no-push.")
    r.add_argument("--since", type=int, default=None, help="Only include jobs posted within the last N days (incremental mode).")
    r.add_argument("-v", "--verbose", action="store_true", help="Verbose DEBUG logging to the log file.")

    d = sub.add_parser("dashboard", help="Regenerate the all-runs HTML dashboard.")
    d.add_argument("--reports", default=str(PROJECT_ROOT / "reports"))
    d.add_argument("--out", default=str(PROJECT_ROOT / "reports" / "dashboard.html"))
    d.add_argument("-v", "--verbose", action="store_true", help="Verbose DEBUG logging to the log file.")
    return p


def _validate_sources(sources: list[str] | None) -> str | None:
    """Return an error message for unknown --source names, else None."""
    if not sources:
        return None
    known = set(all_adapters())
    unknown = [s for s in sources if s not in known]
    if unknown:
        return (
            "Unknown source name(s): " + ", ".join(sorted(unknown))
            + ". Known sources: " + ", ".join(sorted(known))
        )
    return None


def _is_config_error(exc: Exception) -> bool:
    if isinstance(exc, (FileNotFoundError, yaml.YAMLError)):
        return True
    return isinstance(exc, RuntimeError) and str(exc).startswith("Missing required env var")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        setup_logging(logging.DEBUG if args.verbose else logging.INFO)

        if args.command == "run":
            return _cmd_run(args)
        if args.command == "dashboard":
            return _cmd_dashboard(args)
        return 1
    except Exception as exc:
        log.error("command '%s' failed: %s", args.command, exc, exc_info=True)
        if _is_config_error(exc):
            print(f"[jobharness] config error: {exc}", file=sys.stderr)
            return 2
        print(f"[jobharness] {args.command} failed: {exc}", file=sys.stderr)
        return 1


def _cmd_run(args) -> int:
    secrets.load_env(PROJECT_ROOT)
    bad = _validate_sources(args.sources)
    if bad:
        log.error("%s", bad)
        print(f"[jobharness] {bad}", file=sys.stderr)
        return 2

    prof_path = Path(args.profile)
    if not prof_path.exists():
        if prof_path == PROJECT_ROOT / "profiles" / "demo.yaml":
            log.info("profile not found: %s; creating demo profile.", prof_path)
            make_demo_profile(prof_path)
        else:
            raise FileNotFoundError(f"Profile not found: {prof_path}")
    profile = load_profile(prof_path)

    verify_reachable = not args.no_verify and not args.dry_run
    use_llm = not args.no_llm
    push = not args.no_push and not args.dry_run

    result = run_once(
        profile,
        str(PROJECT_ROOT),
        source_filter=args.sources,
        top_n=args.top,
        verify_reachable=verify_reachable,
        use_llm=use_llm,
        push_telegram=push,
        llm_budget=args.llm_budget if args.llm_budget is not None else DEFAULT_LLM_BUDGET,
        since_days=args.since,
    )
    _print_summary(result)
    return 0


def _cmd_dashboard(args) -> int:
    res = build_dashboard(args.reports, args.out)
    log.info("dashboard -> %s", res["out"])
    log.info("  runs: %s  jobs: %s", res["runs"], res["jobs"])
    log.info(
        "  new: %s  closed: %s  avg match: %s",
        res["stats"]["new_count"],
        res["stats"]["closed_count"],
        res["stats"]["avg_match"],
    )
    return 0


def _print_summary(r: dict) -> None:
    log.info("=== RUN SUMMARY ===")
    log.info("Total raw fetched : %s", r["total_raw"])
    log.info("Matched          : %s", r["total_matched"])
    log.info("Genuinely new    : %s", r["report"]["new_count"])
    log.info("Closed/removed   : %s", r["report"]["closed_count"])
    log.info("Empty sources    : %s", r["empty"])
    log.info("Telegram pushed  : %s", r["pushed"])
    log.info("Errors           : %s", r["errors"])
    log.info("HTML report      : %s", r["report"]["html"])
    log.info("CSV report       : %s", r["report"]["csv"])
    log.info("JSON report      : %s", r["report"]["json"])


if __name__ == "__main__":
    raise SystemExit(main())
