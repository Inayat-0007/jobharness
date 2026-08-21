# JobHarness V3 — Improvement Plan

| | |
|---|---|
| **Project** | jobharness — Python job-harvesting, matching & alerting tool |
| **Branch** | V3 (GitHub) — HEAD `62d9646`, 18 commits (all 2026-08-21), working tree clean |
| **Date** | 2026-08-21 |
| **Baseline** | 41 test files / 268 test functions · 26 run directories in `reports/` · 19 adapters · Python ≥3.10 |
| **Status** | **PLAN ONLY** — no source code is modified by this document; all tasks below are executed in follow-up work |

## 1. Executive Summary

JobHarness works end-to-end today: 19 adapters harvest 1,158–1,191 raw jobs per production run (profile `my-target-live.yaml`, India fresher / on-site), which are pre-deduped, LLM-extracted (budget 200), verified, enriched, deduplicated, ranked and pushed to Telegram. But only ~7 jobs match per run and ~0 are genuinely new on reruns, while the run is dominated by serialized bottlenecks: 7 gated browser sources share one global lock (up to 70 min worst-case CAPTCHA waits), dedupe performs N+1 SQLite round trips with pure-Python fuzzy scoring, every request spins up a fresh `httpx.Client`, and verification has no retry so transient failures permanently CLOSE jobs. V3 makes the pipeline measurably faster, more accurate and observable — without changing its thread-based architecture — via 8 workstreams in 3 phases, every task carrying an acceptance criterion.

**Five pillar goals:**

| Pillar | Target (measurable) |
|---|---|
| **SPEED** | Full run ≤45 min typical (gated sources ≤25 min worst case, non-gated ≤15 min); dedupe stage ≥50% faster; all SQLite writes batched |
| **ACCURACY** | ≥90% of jobs carry non-empty descriptions; dedupe precision ≥0.95 / recall ≥0.90 on a labeled set; zero hash collisions for C++ / C# / Node.js variants |
| **RELIABILITY** | Verify retry policy: ≥2 retries with backoff on timeout/DNS/5xx → false-CLOSED rate <5%; 100% of sources report explicit OK/EMPTY/ERROR status; every run writes a log + manifest |
| **SCALABILITY** | One shared pooled HTTP client across the pipeline; bounded parallelism via `--workers`; pagination for API/RSS sources; Telegram pushes via `sendMediaGroup` (≤3 POSTs) |
| **OPERABILITY** | Structured logging + CLI exit codes + run timeout budget; dashboard incremental (SQLite-backed) with <2 s load at 100 runs; `jobharness eval` wired to the existing evaluation/ package |

## 2. Current State Assessment

### 2.1 Pipeline architecture (text diagram)

```
fetch ──► pre-dedup ──► extract+match ──► verify ──► enrich ──► dedupe ──► rank ──► reports ──► Telegram
(4 wkr)   (seq)         (4 wkr)         (6 wkr)    (seq)      (seq)      (seq)   HTML/CSV/JSON/PDF   (seq)
            │              │               │           │           │                                  │
            │              └─ LLM budget 200 (threading.Lock, provider = deepseek)
            │                                 │           │           └─ SQLite jobs.db, per-job commits
            │                                 │           └─ _backfill_descriptions re-parses ALL reports/*/report.json
            └─ browser sources: 7 gated adapters serialized by ONE global _BROWSER_LOCK (browser.py:16,380)
```

### 2.2 Concurrency map

| Stage | Workers | Mechanism | Notes |
|---|---|---|---|
| fetch | 4 | `ThreadPoolExecutor` | one `httpx.Client` per request (no pooling); unbounded futures submitted at once |
| pre-dedup | 1 (seq) | `(title, company)` key | collapses distinct postings with same title+company in different cities |
| extract+match | 4 | executor + LLM lock (budget 200) | LLM output replaces source fields unchecked |
| verify | 6 | executor | no retry; transient failure → CLOSED forever |
| enrich | 1 (seq) | sequential | linkedin_guest caps at 20 jobs; career_page_browser `_detail_cap=15` |
| dedupe | 1 (seq) | per-job SQLite round trips, 25 fuzzy candidates, pure-Python jaro_winkler | N+1; re-reads all historical report.json |
| rank / reports / telegram | 1 (seq) | — | telegram = one HTTP POST per card |
| gated browsers (7 adapters) | 1 (serialized) | single `_BROWSER_LOCK` | worst case 600 s × 2 × 7 sources ≈ 70 min |

### 2.3 Baseline metrics (from real runs)

| Metric | Value |
|---|---|
| Raw jobs per run | 1,158–1,191 |
| Matched (production profile) | ~7 |
| Genuinely new per rerun | ~0 |
| Run directories in `reports/` | 26 |
| Tests | 268 functions / 41 files (README stale at 185) |
| Adapters | 19 (7 gated browser, 6 API/RSS, 3 career page, google_jobs, linkedin_guest, jobposting_ld) |

### 2.4 Top 15 issues ranked by impact

| # | Issue | Category | Location |
|---|---|---|---|
| 1 | 7 gated sources serialized by one lock; up to 70 min CAPTCHA waits | Speed | browser.py:16,380 |
| 2 | Triple-fetch per job URL: adapter → enrich → verify | Speed/cost | runner.py, verify.py, enrich stage |
| 3 | N+1 dedupe: per-job SQLite round trips + 25 fuzzy candidates, single-threaded | Speed | runner.py:228-255, dedupe.py:325-361, algo.py:62-108 |
| 4 | New `httpx.Client` per request — no connection pooling | Speed | fetcher.py:28-41, verify.py:73, llm/provider.py:71, telegram.py:45 |
| 5 | Verify has no retry; transient failures permanently CLOSE jobs | Reliability/accuracy | verify.py:73-86 |
| 6 | Gated adapters swallow all exceptions → `[]` (EMPTY, not ERROR) | Reliability | naukri.py:40-45, internshala.py:33, hirist.py:39, linkedin.py:44, wellfound.py:39, glassdoor.py:28, indeed.py:28 |
| 7 | Enrichment caps starve late jobs of descriptions → worse matching | Accuracy | linkedin_guest.py:117, browser_generic.py:59 |
| 8 | LLM output replaces title/company/location/date with no consistency check | Accuracy | extractor.py:86-101 |
| 9 | `_backfill_descriptions` re-parses every historical report.json on each run | Speed | dedupe.py:129-174 |
| 10 | CLOSED-first sightings suppress future alerts forever | Accuracy | dedupe.py:310 |
| 11 | Dedupe exceptions swallowed per job → job never persisted → re-alerted every run | Reliability | runner.py:252-253 |
| 12 | Everything downstream is sequential: telegram per-card POSTs, greenhouse boards, weworkremotely feeds, career-page seeds | Speed | telegram.py:82-93, greenhouse.py, weworkremotely.py |
| 13 | Empty descriptions bypass the keyword filter entirely | Accuracy | matcher.py:79-83 |
| 14 | Hash normalization strips punctuation: "C++"→"c", "C#"→"c", Node.js/Nodejs collisions | Accuracy | models.py:13-19 |
| 15 | No top-level error handling, no logging subsystem, no run timeout | Operability | cli.py:51-62,66; runner.py:96,253 |

### 2.5 Target concurrency map (V3 end-state)

```
fetch ──► pre-dedup ──► extract+match ──► verify ──► enrich ──► dedupe ──► rank ──► reports ──► Telegram
(4 wkr)   (seq, key +   (4 wkr)         (6 wkr,    (N wkr,   (N chunks,  (seq)   (batched     (sendMediaGroup
           location)                     retries)   no caps)   WAL+retry)          SQLite)      ≤3 POSTs)
```

| Stage | Workers | V3 change |
|---|---|---|
| fetch | 4 (configurable) | shared pooled client; pagination; bounded queue |
| pre-dedup | 1 | key gains city/location + normalized company |
| extract+match | 4 | LLM consistency check; precompiled matcher |
| verify | 6 (configurable) | retry with backoff; DEGRADED instead of CLOSED |
| enrich | parallel sub-workers | caps profile-configurable; ≥90% descriptions |
| dedupe | parallel chunks | batched commits; cached backfill; cap 50 + blocking |
| rank / reports | 1 | single to_dict; batched inserts |
| telegram | 1 | sendMediaGroup; 429 backoff; failure counters |
| gated browsers | 1 dedicated executor | per-source status; no silent `[]`; reduced CAPTCHA wait |
## 3. V3 Goals & Non-Goals

### 3.1 Measurable goals

| Metric | Current | V3 target | How measured |
|---|---|---|---|
| Full-run wall clock | ~30–90 min (gated worst case ~70) | ≤45 min typical; gated ≤25 min | runner timing + run manifest |
| Non-gated pipeline (fetch→reports) | est. 15–25 min | ≤15 min | stage timestamps in manifest |
| Dedupe stage time | N+1, single-threaded | ≥50% faster | `time` around dedupe stage |
| Jobs with non-empty description | ~75% (est.; enrich capped) | ≥90% | SQL `count(description)` on jobs.db |
| Verify false-CLOSED rate | ~100% on transient failure | <5% | verify retry log vs later recovery |
| Dedupe precision / recall (labeled set) | unmeasured | ≥0.95 / ≥0.90 | `jobharness eval` on labeled set |
| Hash collisions (C++, C#, Node.js) | C++/C#→"c"; Node variants collide | 0 collisions | normalization unit test |
| HTTP clients per request | 1 new per request | 1 shared pooled client | code audit + tests |
| Sources with explicit status | 0 (silent `[]`) | 100% | run manifest completeness |
| Telegram POSTs per run | 1 per card | ≤3 batched (`sendMediaGroup`) | notify log |
| Test count / CI | 268 tests, no CI | ≥300 tests, CI green | pytest in GitHub Actions |
| Dashboard load (100 runs) | all JSON in memory | <2 s, flat memory | load benchmark |

### 3.2 Non-goals (explicitly out of scope for V3)

- **No CAPTCHA solving** and no credentials/auto-login storage — gated adapters remain best-effort but must report explicit status.
- **No async rewrite** — the threaded-executor model stays; gains come from de-serialization, pooling and batching.
- **No ML model training** in V3 — calibration of existing weights (Platt scaling, Fellegi–Sunter) is in scope; re-training is not.
- **No new job sources** beyond the existing 19 adapters, and **no database engine change** — SQLite stays, hardened (WAL, retries, checkpoint).
- **No dashboard UI framework change** — static HTML stays; fix aggregation, performance and theming only.## 4. Workstreams (the plan body)

## 4. Workstreams (the plan body)
### WS-1 Speed & Parallelism — Priority P0

**Objective:** Cut run time ≥50% by eliminating serial bottlenecks: pooled HTTP, bounded parallelism, batched SQLite, parallel dedupe/enrichment/telegram.

**Files touched:** `fetcher.py`, `runner.py`, `dedupe.py`, `verify.py`, `notify/telegram.py`, `browser.py`, `sources/career_page/browser_generic.py`, `sources/linkedin_guest.py`, `sources/career_page/greenhouse.py`, `sources/rss/weworkremotely.py`, `sources/career_page/generic.py`, `matcher.py`, `cli.py`, `profile.py`

**Tasks:**

1. **[S, P0]** Shared pooled `httpx.Client` (per-process singleton, connection limits, sane timeouts); replace per-request clients at fetcher.py:28-41, verify.py:73, llm/provider.py:71, telegram.py:45.
2. **[S, P0]** Bounded futures submission in runner.py:175,187 — cap in-flight jobs via `ThreadPoolExecutor(max_workers=N)`; add `--workers` CLI flag honored by every stage executor.
3. **[M, P0]** Batch SQLite: single writer connection with WAL; commit per N jobs (e.g., 50) or at stage end; remove per-job commits at dedupe.py:114,123 and report.py (also fix the double `j.to_dict()` per job in report.py).
4. **[M, P0]** Parallelize dedupe: partition jobs into N chunks with per-chunk connections; cache `_backfill_descriptions` result in memory once per run instead of re-reading all reports (dedupe.py:129-174,325-361).
5. **[M, P1]** Parallelize enrichment: make linkedin_guest cap 20 (linkedin_guest.py:117) and career_page_browser `_detail_cap=15` (browser_generic.py:59) profile-configurable; run enrich sub-workers in parallel; target ≥90% of jobs with descriptions.
6. **[M, P1]** Telegram batching: group cards into `sendMediaGroup` payloads (≤10 media per call) — telegram.py:82-93.
7. **[M, P1]** Pagination for API/RSS sources that support it (adzuna page param, remoteok, remotive, jobicy, usajobs) — profile-configurable pages.
8. **[S, P1]** Parallelize remaining sequential fetch loops: 8 greenhouse boards (greenhouse.py), lever boards, 4 weworkremotely category feeds (weworkremotely.py), generic career-page seeds (career_page/generic.py).
9. **[S, P2]** Precompile matcher regexes and allowlist once per run (matcher.py:30,102-115).
10. **[L, P2]** Benchmark the jaro_winkler hot loop (algo.py:62-108); if >30% of dedupe time, replace with vectorized/cached similarity.

**Acceptance criteria:** non-gated sources ≤15 min; full run ≤45 min typical; dedupe ≥50% faster on the same profile; exactly one shared client per process; ≤3 Telegram POSTs; zero per-job SQLite commits; `--workers` honored by all stages.

### WS-2 Accuracy — Priority P1

**Objective:** Improve match quality and dedupe correctness: stable identity keys, retry-aware verification, refreshed stored rows, sane salary/date/punctuation handling.

**Files touched:** `runner.py`, `extractor.py`, `verify.py`, `models.py`, `dedupe.py`, `matcher.py`, `algo.py`, `sources/` (posting IDs), `identity/posting_id.py`, `identity/company.py`

**Tasks:**

1. **[S, P0]** Pre-dedup key: `(normalized_title, normalized_company, city/location)` instead of title+company only (runner.py:114-121) — keeps distinct postings in different cities.
2. **[M, P1]** LLM override consistency check: adopt LLM-extracted title/company/location/date only when source-derived fields are missing/empty or LLM confidence is high and values are structurally compatible (extractor.py:86-101).
3. **[M, P0]** Retry-aware verify: exponential backoff (≥2 retries) on timeout/DNS/5xx; record `retry_count`; transient failure → status UNKNOWN/DEGRADED, never CLOSED (verify.py:73-86).
4. **[M, P1]** CLOSED-recovery semantics: a job first seen while its source was down must re-alert when later verified AUTHENTIC with new evidence — replace `genuinely_new = authentic_status != "CLOSED"` (dedupe.py:310) with evidence-based logic.
5. **[M, P1]** Raise dedupe candidate cap 25 → 50 and add blocking (bucket candidates by normalized title+company before fuzzy scoring) so true duplicates are not missed (dedupe.py:325).
6. **[M, P1]** Refresh stored title/company/location/description on repeat sightings (upsert) so fuzzy linkage and dashboards use fresh text (dedupe.py:260-295,434-440).
7. **[M, P1]** Salary normalization: parse units (LPA/CTC/annum/hourly) into a comparable annualized number; make the floor check two-sided (matcher.py:91-95).
8. **[M, P1]** Date handling: parse relative dates ("2 days ago") in extractor.py:130-142 and models.py:134-180; prefer ISO/RFC3339; make `%d/%m/%Y` vs `%m/%d/%Y` order configurable; reject future dates from the freshness bonus (models.py:168-169,195-197).
9. **[S, P0]** Punctuation-safe hashing: tokenize on non-alphanumeric separators so C++ ≠ C# and Node.js ≡ Nodejs (models.py:13-19).
10. **[S, P1]** Description-missing handling: do not bypass the keyword filter (matcher.py:79-83); require additional positive signals when description is empty.
11. **[M, P2]** Posting-ID extraction for Naukri, Hirist, Internshala, Wellfound, Google Jobs and RSS sources (identity/posting_id.py — currently only 5 of 19 sources).
12. **[S, P2]** Company normalization for Indian suffixes (Pvt Ltd, LLP) (algo.py:140-151).
13. **[S, P2]** Empty-description similarity: return an informative negative match instead of neutral 0.5 (algo.py:135-137).

**Acceptance criteria:** labeled dedupe precision ≥0.95 / recall ≥0.90; zero C++/C#/Node.js hash collisions; ≥90% jobs with descriptions; false-CLOSED <5%; no alert suppressed forever by one CLOSED sighting; stored rows always current.

### WS-3 Reliability — Priority P0

**Objective:** No silent failures: every exception surfaces as data (log + manifest), verification recovers, the database survives crashes, runs cannot hang forever.

**Files touched:** `cli.py`, `runner.py`, new `logging.py` module, `verify.py`, `dedupe.py`, `fetcher.py`, `browser.py`, `notify/telegram.py`, `sources/api/remoteok.py` (+ other API adapters), `sources/naukri.py` (+ 6 gated adapters)

**Tasks:**

1. **[S, P0]** CLI top-level try/except: friendly error output, exit codes (0 success / 1 error / 2 config), error log file (cli.py:51-62,66).
2. **[M, P0]** Structured logging module (stdlib `logging`, console + rotating file, per-stage/per-source sections); replace all `print()` (runner.py:96,253 and elsewhere).
3. **[M, P0]** Per-source status enum (`OK / EMPTY / ERROR / TIMEOUT / CAPTCHA / SKIPPED`); gated adapters report status instead of swallowing exceptions → `[]` (naukri.py:40-45, internshala.py:33, hirist.py:39, linkedin.py:44, wellfound.py:39, glassdoor.py:28, indeed.py:28); statuses persisted in the run manifest.
4. **[M, P0]** Verify retry with backoff (WS-2 T3) — the single biggest accuracy+reliability lever.
5. **[M, P0]** SQLite hardening: WAL mode, `busy_timeout` ≥30 s, retry wrapper for `_insert`/`_update`/merge, `PRAGMA wal_checkpoint` at end of run (dedupe.py:114,123); prune OPEN rows beyond max_age_days with checkpoint.
6. **[S, P1]** Run timeout budget (profile-configurable, default 60 min): hard deadline, clean abort, partial manifest written.
7. **[S, P1]** Telegram 429 handling: retry with backoff; per-card failure counters surfaced in the run report (telegram.py:55-61,82-93; runner.py:278-284).
8. **[M, P1]** Schema validation for API/RSS adapters (remoteok.py:26 and others): validate response shape; drift → source ERROR, not silent `[]`.
9. **[M, P1]** Browser `page.goto` timeout: retry once, then mark source TIMEOUT/CAPTCHA — never parse a partial DOM silently (linkedin.py:67, indeed.py:57, etc.).
10. **[M, P2]** Proxy health check: ping test before use, fallback list (fetcher.py `pick_proxy`).
11. **[M, P1]** Browser data-dir lockout recovery: stale lock detection + cleanup after crash (browser.py:22,215-269).

**Acceptance criteria:** every run produces a log + manifest with per-source status; zero silent `[]` results; zero bare `except:` remaining; jobs.db survives a simulated mid-run crash (WAL recovery); no run exceeds the budget without a clean partial manifest.

### WS-4 Architecture & Maintainability — Priority P1

**Objective:** Kill duplication and dead code, standardize browser adapters, make constants configurable, restore type safety.

**Files touched:** `browser.py`, `sources/naukri.py`, `sources/internshala.py`, `sources/hirist.py`, `sources/linkedin.py`, `sources/wellfound.py`, `sources/glassdoor.py`, `sources/indeed.py`, `registry.py`, `dedupe.py`, `algo.py`, `dashboard.py`, `evidence/reason.py`, `scoring/authenticity.py`, `extractor.py`, `models.py`, `profile.py`, new `settings.py`

**Tasks:**

1. **[L, P1]** Shared `BrowserPortalAdapter` base class for the 7 gated adapters — open browser → login gate → CAPTCHA gate → selector parse loop, with status propagation (naukri.py, internshala.py, hirist.py, linkedin.py, wellfound.py, glassdoor.py, indeed.py).
2. **[M, P1]** Dynamic adapter registry via decorator (`@adapter("name", ...)`) replacing the static registry list (registry.py:26-52).
3. **[M, P1]** Consolidate `dedupe._update` vs `merge` into one upsert (dedupe.py — the near-identical 24-column UPDATEs).
4. **[S, P2]** Remove dead code: `algo._HAS_RAPIDFUZZ` (algo.py:12), `dashboard._TEXT_TAG` (dashboard.py:14), unused `evidence/reason.py` affiliate_domain signal, unused `verify_result` param in `scoring/authenticity.py`, deferred import in extractor.py:124.
5. **[M, P2]** Type hints across models.py (bare list/dict), runner helpers, algo.py.
6. **[M, P1]** Move hardcoded constants to `settings.py`/profile: worker counts 4/4/6, verify timeout 20 s, delay 0.5–2.0 s, candidate limit 25, max_age_days 90, freshness thresholds 1/7/30.
7. **[S, P1]** India-first browser defaults: timezone `Asia/Kolkata`, locale `en-IN` (browser.py:197-198).
8. **[M, P2]** Consolidate domain normalization (3 places) and date parsing (`_parse_date` vs `normalize_date`) into single implementations.

**Acceptance criteria:** each gated adapter ≤150 lines and inherits status semantics; registry auto-discovers adapters; ruff + mypy clean; zero references to removed code; no hardcoded tuning constants outside settings/profile.

### WS-5 Reporting & Dashboard — Priority P1

**Objective:** Make reporting incremental and the dashboard fast at scale; stabilize PDF/HTML output.

**Files touched:** `dashboard.py`, `report.py`, new SQLite run-summary table

**Tasks:**

1. **[M, P1]** Incremental aggregation: maintain a SQLite run-summary table; dashboard reads summary + per-run rows instead of loading all `reports/*/report.json` into memory and re-parsing every description (dashboard.py:26-46,361).
2. **[S, P2]** Per-run comparison view (delta vs previous run: new matches, re-alerts, status changes).
3. **[S, P2]** CSV export of any run.
4. **[S, P1]** `report.py`: single `j.to_dict()` per job; batched SQLite inserts.
5. **[S, P2]** PDF stability: pinned layout, tolerate missing images (report.py).
6. **[S, P2]** Dark theme.

**Acceptance criteria:** dashboard loads <2 s with 100 runs and flat memory; per-run delta view works; CSV export round-trips; PDF renders cleanly across the 26-run corpus.

### WS-6 Testing & CI — Priority P1

**Objective:** A trustworthy automated quality gate plus regression fixtures for parsing, dedupe and browser adapters.

**Files touched:** new `tests/conftest.py`, new `.github/workflows/ci.yml`, `tests/`, `README.md`

**Tasks:**

1. **[S, P0]** `conftest.py` with shared fixtures and pytest markers (`browser`, `ml`, `integration`) so the suite is deterministic without live network/browser.
2. **[S, P0]** GitHub Actions CI: ruff lint, mypy typecheck, pytest on Python 3.10–3.13; branch protection requires green.
3. **[M, P1]** Golden-fixture tests for adapter parsing (canned HTML/JSON per adapter, covering the fragile selectors at indeed.py:95-107, glassdoor.py:88-96, naukri.py:110-120, hirist.py:110-115, wellfound.py:98-108).
4. **[S, P1]** Dedupe benchmark script: N jobs vs wall time (or pytest-benchmark).
5. **[S, P1]** Dedupe load test: 5,000 synthetic jobs through the stage.
6. **[M, P1]** Mock-based browser adapter tests (no live pages): open→gate→parse flow with fake DOM.
7. **[S, P2]** Update README: correct test count (268, not 185), badges, V3 feature list.

**Acceptance criteria:** CI green within 10 min; test count ≥300; dedupe load test <30 s for 5k jobs; all browser adapters covered by fixture/mock tests.

### WS-7 Operations & Delivery — Priority P2

**Objective:** Production ergonomics: batched notifications, LLM resilience, incremental runs, refreshed docs.

**Files touched:** `notify/telegram.py`, `llm/provider.py`, `runner.py`, `cli.py`, `docs/SETUP.md`, optional `Dockerfile`

**Tasks:**

1. **[M, P1]** Telegram `sendMediaGroup` batching with caption/size limits (telegram.py:82-93).
2. **[M, P2]** Multi-provider LLM load-balancing (round-robin) with per-provider budget and failover (llm/provider.py).
3. **[M, P2]** `--since` incremental wrapper: re-fetch only changed/new sources and re-run dedupe on new sightings.
4. **[S, P2]** Optional Dockerfile (browser dependencies make it heavy — document the trade-off).
5. **[S, P2]** Docs refresh: SETUP.md, profile reference (`my-target-live.yaml` fields), env var table.

**Acceptance criteria:** Telegram push ≤3 POSTs; LLM failover works when the primary provider errors; `--since` documented and tested; SETUP.md matches reality.

### WS-8 Data & Evaluation — Priority P2

**Objective:** Wire the existing evaluation/ machinery into production, calibrate thresholds on real data, fix scoring bugs.

**Files touched:** `evaluation/benchmark.py`, `evaluation/dataset.py`, `evaluation/metrics.py`, `evaluation/calibration.py`, `evaluation/fellegi_sunter.py`, `scoring/thresholds.py`, `scoring/authenticity.py`, `scoring/matching.py`, `algo.py`, `evidence/source.py`, `cli.py`

**Tasks:**

1. **[M, P2]** `jobharness eval` CLI command wiring evaluation/ modules (benchmark.py, dataset.py, metrics.py).
2. **[M, P2]** Collect labeled data from real runs (store verdict + evidence in jobs.db or a dedicated eval table).
3. **[M, P2]** Calibrate thresholds with `platt_scale` + `fellegi_sunter` on the labeled set; persist results into scoring/thresholds.py.
4. **[M, P2]** Replace BM25 idf=1.0 with corpus-derived idf (matching.py:47-53, algo.py:380-395).
5. **[M, P2]** Data-driven authenticity weights (scoring/authenticity.py:14-22); `use_ml` flag stays false until calibration lands.
6. **[S, P1]** Fix `source_authority` inversion: known portals must score ≥ UNKNOWN (evidence/source.py:46-51).

**Acceptance criteria:** `jobharness eval` runs on the labeled set with precision/recall output; thresholds versioned in repo with an eval report; BM25 uses corpus idf; source_authority ordering correct.## 5. Execution Roadmap

## 5. Execution Roadmap
| Phase | Weeks | Workstreams | Exit criteria |
|---|---|---|---|
| **P0 — Speed & Safety** | 1–2 | WS-1 core (T1–T4), WS-3 core (T1–T6), WS-6 T1–T2 pulled forward | Full run ≤45 min; zero silent failures; log + manifest on every run; WAL + retries in place; CI scaffold green |
| **P1 — Accuracy & Architecture** | 3–5 | WS-2 (all), WS-4 (all), WS-3 remaining, WS-6 T3–T7 | Labeled precision ≥0.95 / recall ≥0.90; ≥90% descriptions; adapter refactor done; constants config-driven; fixture suite green |
| **P2 — Operability & Data** | 6–8 | WS-5, WS-7, WS-8, WS-6 final, docs | Dashboard <2 s; Telegram ≤3 POSTs; `jobharness eval` operational; README/docs current; ≥300 tests CI green |

**Dependency notes (ordering constraints):**

- Shared pooled `httpx.Client` (WS-1 T1) **must precede** parallel verify/enrichment (WS-1 T4–T5) — pooling and connection limits interact with concurrency.
- Logging subsystem (WS-3 T2) **must precede** dedupe parallelization (WS-1 T4) — multi-thread debugging is impossible with `print()`.
- SQLite WAL + retry wrapper (WS-3 T5) **must precede** any parallel SQLite access.
- `BrowserPortalAdapter` base class (WS-4 T1) **must precede** browser selector hardening (WS-3 T9) so retry/status semantics live in one place.
- WS-6 CI wraps all phases — every PR keeps lint/typecheck/tests green; conftest.py lands in week 1.

**P0 — Speed & Safety, week by week**

| Week | Deliverables |
|---|---|
| 1 | WS-6 T1–T2 (conftest + CI scaffold); WS-1 T1 (shared httpx client); WS-3 T1–T2 (CLI error handling, logging subsystem) |
| 2 | WS-1 T2–T4 (bounded futures, batched SQLite, parallel dedupe — requires week-1 logging); WS-3 T3–T6 (per-source status, verify retry, WAL hardening, run timeout) |

**P1 — Accuracy & Architecture (weeks 3–5):** WS-2 T1–T13, WS-4 T1–T8, WS-3 T7–T11, WS-6 T3–T7. Exit: labeled precision/recall targets met, adapter refactor complete, ≥300 tests green.

**P2 — Operability & Data (weeks 6–8):** WS-5 (dashboard), WS-7 (operations), WS-8 (evaluation), final docs. Exit: dashboard <2 s, Telegram ≤3 POSTs, `jobharness eval` operational.
## 6. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Playwright used from worker threads (browser.py:382, browser_generic.py:79-87) is not thread-safe | High | High | Keep browser work on a dedicated single-thread executor; per-source isolated profiles; mock tests lock behavior |
| Portal ToS / blocking escalation on gated sources | Medium | High | Rate limits, respect robots.txt, profile rotation, explicit CAPTCHA status — no solving |
| LLM cost grows with full enrichment | Medium | Medium | Per-provider budget, cheaper model for enrichment, cache LLM outputs |
| SQLite concurrency issues from parallel dedupe | Medium | Medium | WAL, single writer, per-chunk connections, retry wrapper, end-of-run checkpoint |
| Selector drift in browser adapters | High | Medium | Golden fixtures, schema validation, ERROR status instead of silent `[]` |
| Threshold calibration regression | Medium | High | `jobharness eval` before/after every calibration; versioned thresholds |
| Parallelism introduces flaky tests | Medium | Medium | Deterministic fixtures, no live network in CI, `integration` marker |

## 7. Success Metrics & KPIs

| KPI | Target |
|---|---|
| Time-to-run reduction | ≥50% (gated ≤25 min, full run ≤45 min) |
| % jobs with descriptions | ≥90% |
| Dedupe precision / recall on labeled set | ≥0.95 / ≥0.90 |
| Verify false-CLOSED rate | <5% |
| Alert quality (`genuinely_new` fraction of alerts) | >5% (from ~0) — proves CLOSED-recovery alerts work |
| Silent failure rate | 0 (manifest complete with per-source status) |
| Test count / CI | ≥300 tests, CI green on every commit |
| Dashboard performance | <2 s load at 100 runs, flat memory |
| Telegram efficiency | ≤3 POSTs per run |

## 8. Appendix A: Baseline Inventory

### A.1 Adapters (19)

| Adapter | Type | Fetch mechanism | Enabled (default) |
|---|---|---|---|
| remoteok | API | httpx GET (JSON) | yes |
| adzuna | API | httpx GET (`adzuna_country=in`) | yes |
| usajobs | API | httpx GET + auth | no |
| weworkremotely | RSS | feedparser (4 category feeds) | yes |
| remotive | RSS | feedparser | yes |
| jobicy | RSS | feedparser | yes |
| greenhouse | career-page API | httpx GET (8 boards in prod profile) | yes |
| lever | career-page API | httpx GET — **deprecated, returns 404** | no |
| career_page_generic | scraping | httpx GET (46 pages in prod profile) | yes |
| career_page_browser | scraping | Playwright, 4 workers + 5 enrich sub-workers, `_detail_cap=15` | yes |
| google_jobs | scraping | httpx GET + `time.sleep(2**attempt)` backoff | yes |
| linkedin_guest | scraping | httpx GET, 6 enrich sub-workers, cap 20 | yes |
| linkedin | gated browser | Playwright (serialized) | **no** |
| indeed | gated browser | Playwright (serialized) | **no** |
| glassdoor | gated browser | Playwright (serialized) | **no** |
| naukri | gated browser | Playwright (serialized) | yes |
| internshala | gated browser | Playwright (serialized) | yes |
| hirist | gated browser | Playwright (serialized) | yes |
| wellfound | gated browser | Playwright (serialized) | yes |

### A.2 Production profile (`my-target-live.yaml`)

| Setting | Value |
|---|---|
| Scope | India-only, on-site, 0–1 yr fresher |
| Roles / keywords | 30 roles / 47 keywords; senior excludes |
| Sources enabled | 9: remoteok, weworkremotely, remotive, jobicy, greenhouse, career_page_browser, adzuna, google_jobs, linkedin_guest |
| Boards / career pages | 8 greenhouse boards / 46 career pages |
| LLM provider / budget | deepseek / 200 |
| Adzuna country / top_n | `in` / 50 |

### A.3 Source file inventory (line counts at HEAD 62d9646)

| File | Lines | File | Lines |
|---|---|---|---|
| jobharness/runner.py | 281 | jobharness/browser.py | 368 |
| jobharness/dedupe.py | 444 | jobharness/algo.py | 379 |
| jobharness/dashboard.py | 357 | jobharness/models.py | 182 |
| jobharness/verify.py | 139 | jobharness/extractor.py | 120 |
| jobharness/fetcher.py | 62 | jobharness/matcher.py | 101 |
| jobharness/cli.py | 72 | jobharness/registry.py | 47 |
| jobharness/profile.py | 122 | jobharness/report.py | 118 |
| jobharness/urlutil.py | 50 | jobharness/secrets.py | 21 |
| jobharness/llm/provider.py | 95 | jobharness/notify/telegram.py | 77 |
| jobharness/evidence/source.py | 43 | jobharness/evidence/reason.py | 29 |
| jobharness/evidence/positive.py | 27 | jobharness/evidence/negative.py | 39 |
| jobharness/identity/posting_id.py | 41 | jobharness/identity/title.py | 11 |
| jobharness/identity/company.py | 22 | jobharness/identity/location.py | 6 |
| jobharness/scoring/matching.py | 103 | jobharness/scoring/decision.py | 54 |
| jobharness/scoring/authenticity.py | 19 | jobharness/scoring/thresholds.py | 44 |
| jobharness/evaluation/benchmark.py | 89 | jobharness/evaluation/dataset.py | 122 |
| jobharness/evaluation/metrics.py | 36 | jobharness/evaluation/calibration.py | 31 |
| jobharness/evaluation/fellegi_sunter.py | 50 | jobharness/sources/api/remoteok.py | 44 |
| jobharness/sources/api/adzuna.py | 88 | jobharness/sources/api/usajobs.py | 66 |
| jobharness/sources/rss/weworkremotely.py | 48 | jobharness/sources/rss/remotive.py | 44 |
| jobharness/sources/rss/jobicy.py | 35 | jobharness/sources/career_page/greenhouse.py | 73 |
| jobharness/sources/career_page/lever.py | 58 | jobharness/sources/career_page/generic.py | 40 |
| jobharness/sources/career_page/browser_generic.py | 190 | jobharness/sources/linkedin_guest.py | 142 |
| jobharness/sources/linkedin.py | 163 | jobharness/sources/indeed.py | 122 |
| jobharness/sources/glassdoor.py | 108 | jobharness/sources/naukri.py | 150 |
| jobharness/sources/internshala.py | 126 | jobharness/sources/hirist.py | 147 |
| jobharness/sources/wellfound.py | 119 | jobharness/sources/google_jobs.py | 62 |
| jobharness/sources/jobposting_ld.py | 128 | jobharness/sources/base.py | 11 |
| jobharness/sources/exceptions.py | 13 | tests/ (41 files) | — |

### A.4 Test inventory

41 test files, 268 test functions. Coverage areas: adapters (remoteok, adzuna, usajobs, weworkremotely, remotive, jobicy, greenhouse, lever, google_jobs, linkedin_guest, sources smoke), pipeline (runner e2e, runner dedup, dedupe, dedupe_v3, dedupe_migration), scoring/matching (matcher, matching, algo, decision, freshness, verify, verify_confidence), identity/evidence (identity, evidence, normalize_date, jobposting_ld), reporting (report, report_escape, telegram_html, telegram_file, dashboard, source_status), infra (registry, llm_provider, secrets_cli_profile, evaluation, browser_gates, allowlist_split, urlutil). No conftest.py, no markers/skips, suite not run recently.

### A.5 Environment variables (via python-dotenv / secrets.py)

`BROWSER_USER_DATA_DIR` (shared Playwright profile — lockout cascade risk after crash), Telegram bot token + chat id, LLM provider API keys (deepseek), usajobs API keys, proxy variables consumed by `fetcher.pick_proxy`, profile file path. Canonical list lives in `secrets.py` (21 lines) and docs.

### A.6 Dependencies (pyproject extras)

| Dependency | Use | V3 note |
|---|---|---|
| httpx | fetch / verify / LLM / telegram HTTP | per-request clients today → WS-1 T1 pooling |
| pyyaml, python-dotenv | profile + env config | profile my-target-live.yaml |
| beautifulsoup4, lxml | HTML parsing | dashboard re-parses all descriptions (dashboard.py:361) |
| feedparser | RSS (weworkremotely, remotive, jobicy) | no pagination; schema validation needed (WS-3 T8) |
| playwright, playwright-stealth | gated browser adapters | thread-safety risk; shared BROWSER_USER_DATA_DIR |
| jinja2 | HTML report templates | |
| extra telegram: python-telegram-bot (legacy) | Telegram notify | no 429 handling (WS-3 T7) |
| extra dev: pytest, pytest-asyncio, ruff, mypy | tests / lint / typecheck | CI targets (WS-6) |
| extra ml: scikit-learn, numpy | evaluation/ calibration + BM25 | not wired into production; use_ml=false (WS-8) |

### A.7 Fragile hotspots map

| Hotspot | Risk | Location |
|---|---|---|
| Hardcoded CSS selectors on gated portals | silent empty parse on redesign | indeed.py:95-107, glassdoor.py:88-96, naukri.py:110-120, hirist.py:110-115, wellfound.py:98-108 |
| Internshala listing slug regex | fragile | internshala.py:129-136 |
| RemoteOK response shape drift | silent [] | remoteok.py:26 |
| Shared browser profile lockout | cascade after crash | browser.py:22,215-269 |
| 67 `except Exception` sites, several bare excepts | swallowed errors | package-wide |
## 9. Appendix B: Quick Wins (day-1 items)

| # | Fix | Location | Expected effect |
|---|---|---|---|
| 1 | Batch SQLite commits per stage instead of per job | dedupe.py:114,123 | Largest single dedupe speedup |
| 2 | Precompile matcher regexes + allowlist once per run | matcher.py:30,102-115 | Small steady CPU cut |
| 3 | Punctuation-safe hash tokenization | models.py:13-19 | Fixes C++/C#/Node.js collisions |
| 4 | Fix `source_authority` inversion (known portals > UNKNOWN) | evidence/source.py:46-51 | Correct scoring order |
| 5 | Parse relative dates ("2 days ago") | models.py:134-180, extractor.py:130-142 | Better freshness scoring |
| 6 | Reject future dates in freshness bonus | models.py:195-197 | No phantom freshness |
| 7 | Top-level CLI try/except + exit codes | cli.py:51-62 | No raw tracebacks |
| 8 | Raise dedupe candidate cap 25 → 50 | dedupe.py:325 | Fewer missed duplicates |
| 9 | Empty descriptions no longer bypass keyword filter | matcher.py:79-83 | Fewer garbage matches |
| 10 | CLOSED-recovery: re-alert on later AUTHENTIC evidence | dedupe.py:310 | Alerts restored after source outages |
