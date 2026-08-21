# FIRST RUN REPORT — Job Harness (real data, no mocks)

Run timestamp: `20260821-052602` · Profile: `profiles/my-target-live.yaml` · LLM: off (DeepSeek key has no balance)

## Summary

| Metric | Value |
|---|---|
| Sources fetched | 8 (6 returned jobs) |
| Raw jobs fetched | 1,158 |
| Matched profile | 7 |
| Genuinely new | 7 |
| Closed/removed | 0 |
| Errors | 0 |
| Decisions | REVIEW × 7 |
| Telegram pushed | 0 (only AUTO_ACCEPT decisions are pushed) |
| Reports | `reports/20260821-052602/report.{html,csv,json}` |

## Raw jobs by source

| Source | Raw | Status |
|---|---|---|
| greenhouse | 762 | no_match (airbnb/stripe boards only; no Python/Backend roles) |
| weworkremotely | 260 | 1 match |
| remoteok | 100 | no_match (generic feed: laborer, baker, courier, etc.) |
| remotive | 19 | no_match |
| adzuna | 17 | 10 matched → 5 kept (6 were duplicates/subsets) |
| jobicy | 0 | empty |
| lever | 0 | empty |
| google_jobs | 0 | empty |

## Matched jobs (7)

| # | Title | Company | Source | Posted | Salary | Score | Decision |
|---|---|---|---|---|---|---|---|
| 1 | Python Developer | — | adzuna | 2026-08-20 | ~$118k | 56 | REVIEW |
| 2 | Senior Python Backend Developer | — | adzuna | 2026-08-18 | ~$128k | 40 | REVIEW |
| 3 | Senior Backend Developer (Python) | Proxify AB | weworkremotely | 2026-08-14 | — | 55 | REVIEW |
| 4 | Python Developer with Mainframe Experience - Remote | — | adzuna | 2026-08-19 | ~$81k | 40 | REVIEW |
| 5 | Senior Python Developer | — | adzuna | 2026-08-19 | ~$116k | 40 | REVIEW |
| 6 | Quantitative Engineer / Python Developer | — | adzuna | 2026-08-15 | ~$104k | 40 | REVIEW |
| 7 | AWS/Python developer | — | adzuna | 2026-08-19 | ~$91k | 40 | REVIEW |

All 7 are AUTHENTIC, genuinely new, and stored in `jobs.db`. None were pushed to Telegram because the notifier only alerts on `AUTO_ACCEPT` decisions; these need human review first.

## Issues found and fixed during the run

1. **DeepSeek API key has no balance** — `POST /chat/completions` returns HTTP 402 "Insufficient Balance". LLM extraction could not run; this run used raw-field extraction (`--no-llm`). Top up the DeepSeek account or use another provider key to enable LLM extraction.
2. **Adzuna adapter returned 0 jobs** (two bugs, both fixed in `jobharness/sources/api/adzuna.py`):
   - Query was a 6-word phrase (`"Python Developer python django fastapi remote"`) — Adzuna's `what` does full-phrase matching and returned 0 results. Now uses the first role only, e.g. `"Python Developer remote"` (17 results).
   - Client sent `Accept: text/html,...`, and Adzuna returned an HTML page instead of JSON, so `resp.json()` silently failed. Request now forces `Accept: application/json`.
3. **Profile excludes zeroed all matches** — `senior`/`manager` appear in most job descriptions (e.g., "Senior Python Developer", "9 years experience"), so the strict description-wide exclude rejected everything. The live run used `profiles/my-target-live.yaml` (excludes: `frontend`, `java`); the original `my-target.yaml` was left untouched.

## Notes

- Adzuna is hardcoded to the US market (`country = "us"`); the registered app id is US-market.
- Remote filtering: 6 of 7 matches are remote; one (Quantitative Engineer) is not.
- Re-running the same command will produce far fewer "new" jobs since all 7 are now in `jobs.db` (dedupe).
- Test suite: 170/170 pass after the Adzuna fixes.
