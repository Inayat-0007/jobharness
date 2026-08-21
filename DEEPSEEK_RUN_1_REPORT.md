# DEEPSEEK RUN — MOHAMMAD INAYAT HUSSAIN (Job Search Profile)

Run timestamp: `20260821-055131` · Profile: `profiles/my-target-live.yaml` · Provider: **deepseek** (`deepseek-v4-flash` via b.ai) · LLM budget: 80 calls · Location rule: anywhere in India (remote OK) · Level: fresher / MCA-2026 new grad / trainee

## Summary

| Metric | Value |
|---|---|
| Raw jobs fetched | 1,191 (6 live sources) |
| LLM extraction calls | 80 (0 errors) |
| Matched your profile | 7 |
| Genuinely new this run | 0 (already in jobs.db from prior runs — dedupe) |
| Decisions | REVIEW × 2, REJECT × 5 |
| Reports | `reports/20260821-055131/report.{html,csv,json}` |

## Best matches (REVIEW — worth applying)

| Job | Company | Location | Source |
|---|---|---|---|
| Data Engineer (Interior Design) | Sigma Software | Remote | weworkremotely |
| Data Analyst (Wellbeing product) | Kiss My Apps | Remote | weworkremotely |

## Also found (REJECT — lower score, apply with caution)

| Job | Company | Location | Source |
|---|---|---|---|
| Software Engineer, Internal Systems | Stripe | Bengaluru, India | greenhouse |
| Data Engineer – Databricks/AWS | Azumo | Remote (LatAm) | weworkremotely |
| Data Engineer – Latin America | Azumo | Remote (LatAm) | weworkremotely |
| Full Stack AI Engineer | Reveleer | Remote | weworkremotely |
| Software Engineer | Sticker Mule | Remote | weworkremotely |

## How your resume was turned into the profile

`profiles/my-target-live.yaml` now encodes your resume:

- **Roles:** Software Engineer, Data Engineer, AI Engineer, Python Developer, Trainee
- **Skills (keywords):** python, sql, fastapi, react, node.js, javascript, docker, git, genai, llm, langgraph, rag, opencv, snowflake, airflow, neo4j, mongodb, postgresql, mysql, etl, mcp, onnx, streamlit, dbt, cnn, machine learning, deep learning, ai/ml, backend
- **Excludes (fresher focus):** senior, lead, principal, staff, architect, director, head of, vp, cto, manager, 10+ years, 15+ years
- **Location:** India anywhere (new location filter enforces this), remote jobs still pass
- **Company boards:** cleared so all companies are considered (previously locked to airbnb/stripe)
- **Adzuna market:** India (`adzuna_country: in`)

## Code changes this session (for your India job search)

1. `jobharness/matcher.py` — **location filter**: `profile.location` now enforced. Jobs in other countries (Toronto, Seattle, London, Dublin, Bucharest, Chicago, Brazil) are rejected; India + remote jobs pass.
2. `jobharness/sources/api/adzuna.py` — `adzuna_country` comes from the profile (`in` for India); each job's location is tagged with the country name (e.g. "Bengaluru, Karnataka, India") so the location filter works.
3. `jobharness/profile.py` — new `adzuna_country` field (default `us`).
4. `jobharness/runner.py` — extraction parallelized (4 workers) with thread-safe LLM budget; likely-matching jobs are extracted first so the budget isn't wasted.
5. `jobharness/cli.py` — new `--llm-budget N` flag.

## Source reality check (India fresher market)

- **Adzuna India:** API works (3,278 jobs for "Software Engineer") but the top-50 newest are mostly senior/lead roles or Java/C#/Spring tech → correctly filtered out. Fresher-friendly postings are rare on the feed.
- **Greenhouse (Stripe/Airbnb boards):** mostly mid-senior global roles; Bengaluru office has some entry software engineer roles.
- **weworkremotely / remotive / remoteok:** global remote boards — good for remote data/software roles, which your profile accepts.
- **LinkedIn / Indeed / Glassdoor:** disabled (require keys/scraping). These would dramatically improve Indian fresher coverage — consider adding keys.

## How to use

- Open `reports/20260821-055131/report.html` (interactive) or `report.csv` for full details and apply URLs.
- Fresh postings from these sources will be picked up automatically on each run; already-seen jobs are not re-reported.
- Recommended rerun cadence: daily; add `--llm-budget 80` to keep cost/time low.
- To widen results, add more roles (e.g. "Graduate Trainee", "Associate Software Engineer") and consider enabling more sources with keys.

Tests: 170/170 pass.
