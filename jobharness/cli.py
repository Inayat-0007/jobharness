from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import secrets
from .profile import load_profile, make_demo_profile
from .runner import run_once


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobharness", description="On-demand job harvest harness.")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Run one harvest pass.")
    r.add_argument("--profile", default=str(PROJECT_ROOT / "profiles" / "demo.yaml"))
    r.add_argument("--source", action="append", dest="sources", help="Only run these source names (repeatable).")
    r.add_argument("--top", type=int, default=None)
    r.add_argument("--no-llm", action="store_true", help="Skip LLM extraction (use raw fields only).")
    r.add_argument("--no-verify", action="store_true", help="Skip apply-URL reachability check.")
    r.add_argument("--no-push", action="store_true", help="Skip Telegram push.")
    r.add_argument("--dry-run", action="store_true", help="Alias for --no-verify --no-push.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "run":
        secrets.load_env(PROJECT_ROOT)
        prof_path = Path(args.profile)
        if not prof_path.exists():
            print(f"[jobharness] profile not found: {prof_path}; creating demo profile.")
            prof_path = PROJECT_ROOT / "profiles" / "demo.yaml"
            make_demo_profile(prof_path)
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
        )
        _print_summary(result)
        return 0

    return 1


def _print_summary(r: dict) -> None:
    print("\n=== RUN SUMMARY ===")
    print(f"Total raw fetched : {r['total_raw']}")
    print(f"Matched          : {r['total_matched']}")
    print(f"Genuinely new    : {r['report']['new_count']}")
    print(f"Closed/removed   : {r['report']['closed_count']}")
    print(f"Blocked sources  : {r['blocked']}")
    print(f"Telegram pushed  : {r['pushed']}")
    print(f"Errors           : {r['errors']}")
    print(f"HTML report      : {r['report']['html']}")
    print(f"CSV report       : {r['report']['csv']}")
    print(f"JSON report      : {r['report']['json']}")


if __name__ == "__main__":
    raise SystemExit(main())
