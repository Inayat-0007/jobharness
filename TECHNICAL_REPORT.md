# MASTER MEGA TECHNICAL REPORT — `jobharness`

## 0. Metadata & Environment

| Item | Value |
|---|---|
| **Report generated** | 2026-08-21 04:22 IST (Asia/Kolkata, UTC+05:30) |
| **Last activity in repo** | 2026-08-21 04:21 IST (commit `c7b092d`) |
| **Host platform** | Windows (PowerShell 5.1), x64 |
| **Working directory** | `C:\Users\moham\jobharness` |
| **Project** | `jobharness` v0.1.0 — "On-demand job harvest harness" |
| **Python requirement** | `>=3.10` |
| **Single author** | `Inayat-0007` (5 commits) |
| **Python runtime** | All modules import cleanly; local `.venv` used |

---

## 1. GIT REPO STATUS

### 1.1 Branch & Remote
- **Branch:** `main` — pushed to `origin/main`
- **Remote:** `https://github.com/Inayat-0007/jobharness.git` (origin, fetch+push)

### 1.2 Working Tree
```
On branch main
Untracked files:
	.kilo/
	profiles/my-target.yaml
```
- **Untracked, intentionally:** `profiles/my-target.yaml` — the user's personal target profile (roles: Python Developer/Backend Engineer; keywords python/django/fastapi; excludes manager/senior/frontend/java) and `.kilo/` (Kilo tool config — plans/commands, not project code). Both stay out of the repo.
- `jobs.db` / `reports/` remain gitignored (runtime state).

### 1.3 Commit History (5 commits, all 2026-08-21)

| Commit | Time (IST) | Summary | Size |
|---|---|---|---|
| `dde9bc4` | 02:03 | Initial commit: on-demand job harvest harness | +2803 |
| `a62f940` | 02:16 | Fix documented limitations + harden authenticity, scrapers, DB | +1139/-301 |
| `f16cd6b` | 02:21 | Fix Greenhouse dict departments + SETUP.md + free-only profile | +328 |
| `ca0ff6e` | 02:53 | Fix date parsing, company allowlist split, cross-source dedup, HTML escaping; add tests | +537/-69 |
| `c7b092d` (HEAD) | 04:21 | **Identity/authenticity/relevance upgrade:** `algo.py`, URL canonicalization, fuzzy dedup + SQLite v3, three-score model, decision engine, evidence/source statuses, Phase-4 evaluation package | +4711 |

### 1.4 Repository Metrics
- **Source:** 62 Python files, ~4,711 lines (`jobharness/`)
- **Tests:** 27 Python files, ~2,189 lines (`tests/`)
- **Test result (just executed):** `166 passed in ~3.2s` — all green, all offline
- **New packages added in `c7b092d`:** `identity/`, `evidence/`, `scoring/`, `evaluation/` (each purely additive; no existing module reorganized)

---

## 2. EXECUTIVE SUMMARY

`jobharness` is a Python CLI that performs **on-demand job harvesting**: it fans out across 13 pluggable source adapters (API, RSS, ATS career boards, schema.org JSON-LD scraping, login-gated browser automation), extracts structured fields strictly from source content (hard **"no-fabrication" guarantee**), deduplicates across sources AND across runs, verifies that each direct apply URL is reachable and not CLOSED, scores each job on **three independent dimensions** (identity, authenticity, relevance), decides `AUTO_ACCEPT` / `REVIEW` / `REJECT`, and delivers an HTML/CSV/JSON report plus Telegram push (only for AUTO_ACCEPT genuinely-new jobs).

The design philosophy is explicit: **degrade gracefully, never fabricate, prefer conservative over noisy**. Every unknown field becomes the literal string `MISSING`/empty; blocked or failed sources are recorded as typed statuses, not synthesized. The push gate was tightened from `confidence_score >= 50` to `decision == AUTO_ACCEPT` — fewer, higher-confidence alerts by design.

---

## 3. ARCHITECTURE & MODULE LAYER MAP

```
jobharness/
├── cli.py              entry point (argparse) -> run_once
├── runner.py           orchestrator: fetch -> extract -> match -> verify ->
│                       identity/evidence enrichment -> fuzzy dedup -> decide -> report -> push
├── profile.py          Profile dataclass + YAML load/save + allowlist migration + use_ml gate
├── models.py           RawJob, Job dataclasses; job_id_hash; canonical id hierarchy;
│                       fingerprint; date parsing; freshness
├── algo.py             ★ single home for ALL algorithms (pure stdlib, guarded rapidfuzz):
│                       jaro_winkler, token shingles/Jaccard, company/location/description
│                       similarity, composite_similarity, blocking_keys, title_stem,
│                       bm25, authenticity_features, thresholds
├── urlutil.py          ★ URL canonicalization (tracking-param strip, host normalize);
│                       canonical apply-URL domain extraction
├── extractor.py        RawJob->Job; optional LLM field refinement; MISSING contract
├── matcher.py          profile filters (hard rules — authoritative, unchanged)
├── verify.py           reachability, CLOSED detection, confidence + authenticity scoring,
│                       verify-context for evidence builders
├── dedupe.py           SQLite store v3: migration, upsert, find_candidates,
│                       fuzzy_lookup, merge, 90-day CLOSED pruning
├── report.py           Jinja2 HTML (Decision column) + CSV (34 cols) + JSON writers
├── registry.py         adapter registry -> enabled_adapters(profile)
├── fetcher.py          httpx client, UA pool, proxies, block detection + classify_response
├── browser.py          stealth Playwright factory, CAPTCHA gate, cookie persistence
├── secrets.py          .env loader
├── identity/           ★ posting_id extraction, company entity + aliases,
│                       location buckets, title normalization (delegates to algo)
├── evidence/           ★ SourceStatus enum + SOURCE_AUTHORITY map, positive/negative
│                       signal builders, human-readable reason composition
├── scoring/            ★ matching.py (BM25 relevance), decision.py, thresholds.py,
│                       authenticity.py (weighted raw heuristic)
├── evaluation/         ★ Phase-4 GATED: labeled-pair dataset generator, metrics
│                       (PRF/ECE), Platt calibration, Fellegi-Sunter, offline benchmark
├── llm/provider.py     OpenAI-compatible multi-provider (gemini->glm->qwen fallback)
├── notify/telegram.py  Bot API; card shows decision + top reason; AUTO_ACCEPT gate
└── sources/            13 adapters in 4 tiers + exceptions.py (typed fetch errors)
```

**Dependency graph:** `cli -> runner -> {registry, extractor, matcher, verify, dedupe, report, notify, scoring, evidence, identity}` with `models` as the shared leaf type. `algo.py` is imported by models/verify/dedupe/scoring/evidence/identity — it imports nothing from the project at module level (only lazy function-level imports), so there are **no import cycles**.

---

## 4. END-TO-END PIPELINE WALKTHROUGH (`runner.run_once`)

1. **Bootstrap** — loads `.env`, stamps run timestamp, resolves adapters via `enabled_adapters(profile)`.
2. **Concurrent fetch** (`max_workers=4`) — every adapter returns `(name, jobs, err, SourceStatus)`. Typed exceptions (`RateLimitedError`, `AuthRequiredError`, `SourceDownError`, `ParseFailureError`) map to `rate_limited` / `auth_required` / `source_down` / `parse_failure`; empty+no-error → `empty`; generic exception → `source_down`. Sources that fetched jobs but matched none get `no_match`.
3. **Cross-source pre-dedup** — jobs collapsed by `(title.lower(), company.lower())` regardless of source (one extraction, one alert per posting).
4. **Extraction** — `extract(raw, use_llm, llm_provider)`; LLM capped at `DEFAULT_LLM_BUDGET = 200`; beyond that fast no-LLM extraction. Extraction exceptions are logged, never fatal.
5. **Filtering** — `matches_profile(job, profile)` hard rules (excludes, roles, keywords OR, seniority, salary floor, company allowlist). **Unchanged and authoritative — BM25 never overrides an exclusion.**
6. **Verification** (`max_workers=6`) — `verify(job, check_reachable=True)` resolves redirects, scans `CLOSED_MARKERS`, validates employer domain, computes `confidence_score`, sets `authenticity_score`, and stores a `_verify_ctx` (status_code/blocked/closed_marker/redirect) for evidence builders.
7. **Identity + evidence enrichment** — per job: `canonical_url`/`final_url` (`urlutil`), `posting_id` (`identity.posting_id`), `source_authority`, `canonical_job_id`, blocking keys, description fingerprint, authenticity score (recomputed with authority+posting id), positive/negative evidence and reasons.
8. **Dedup + decision (per job, in store order)** — `fuzzy_lookup(job)` against `find_candidates` (exact hash → canonical id → canonical URL/posting id → blocking keys, LIMIT 25):
   - **HIGH** (composite verdict `auto_merge`) → `store.merge()` into the existing row, `genuinely_new=False`, `matched_via=fuzzy`, **no alert**;
   - **MEDIUM** (`review`) → `possible_duplicate_of` set + REVIEW hint;
   - **LOW** → normal path.
   Then `score_match(job, profile)` (BM25 relevance) and `decide(identity, authenticity, match, state)` set `decision` + reasons; the row is persisted via merge/upsert with all v3 columns.
9. **Ranking** — `(decision rank: AUTO_ACCEPT > REVIEW > REJECT/"")`, then `match_score` (fallback `confidence_score`), then freshness, then `first_seen_at` desc.
10. **Reports** — `report.html` (Decision column + top reason) / `.csv` (34 columns) / `.json` under `reports/<run_ts>/`.
11. **Push** — one Telegram card per `decision == AUTO_ACCEPT` AND `genuinely_new` AND not CLOSED, plus the CSV attachment. Summary prints decision counts and per-source statuses.

---

## 5. DATA MODEL (`models.py`)

### 5.1 Identity & Normalization
```python
job_id_hash = sha1(normalize(title) | normalize(company) | normalize(location))   # unchanged, still the PK
compute_canonical_id():  # identity hierarchy, first non-empty wins
  LEVEL 1  posting:{external posting id}
  LEVEL 2  url:{canonical apply URL}
  LEVEL 3  ct:{company entity}|{normalized title}        (location-agnostic; IBM == IBM Corporation)
  LEVEL 4  ct:{raw company}|{title}|{location}
  LEVEL 5  hash:{job_id_hash}                            (never empty)
compute_fingerprint():  sha1 of sorted token shingles (exact, not MinHash)
```
`job_id_hash` is untouched (backward compat); the canonical id enables lookup before upsert.

### 5.2 Constants
`VALID_AUTHENTIC="AUTHENTIC"`, `CLOSED="CLOSED"`, `BLOCKED="BLOCKED"`, `MISSING="MISSING"`.

### 5.3 RawJob vs Job
- `RawJob`: source-level primitive (source_name/url, title, company, location, description, posted_date, apply_url, raw_html, extra dict).
- `Job`: now carries the three-score model: `identity_score` (0-1), `authenticity_score` (0-100), `match_score` (0-1), plus `decision` (`AUTO_ACCEPT`/`REVIEW`/`REJECT`/`""`), `matched_via` (default `"exact"`), `possible_duplicate_of`, `canonical_job_id`, `block_key` (list), `description_fingerprint`, `posting_id`, `original_url`/`canonical_url`/`final_url`, `source_authority` (0-5), `job_version`, `evidence`/`negative_evidence`/`reason` (lists), and `confidence_score` (kept for backward compat).

### 5.4 Date handling
`_parse_date` supports epoch (10/13-digit), RFC-2822, and 10 ISO-8601 formats. `freshness_label` maps age to `fresh`/`recent`/`older`/`stale` with token heuristics for unparseable text.

---

## 6. EXTRACTION & THE "NO FABRICATION" GUARANTEE (`extractor.py`, `llm/provider.py`)

Unchanged from prior baseline: prompt contract forces literal `MISSING` for unknown fields, `temperature=0`, strict JSON recovery, `MISSING` never overwrites defaults, per-run LLM budget 200, provider fallback `gemini -> glm -> qwen`. All 166 tests keep this invariant locked.

---

## 7. SOURCE ADAPTERS (Tier Breakdown)

Unchanged (13 adapters in 4 tiers): Tier 1 API/RSS (remoteok, weworkremotely, remotive, jobicy, adzuna, usajobs), Tier 4 career pages (greenhouse, lever, career_page_generic + shared `jobposting_ld` parser), Tier 3 Google for Jobs, Tier 5 login-gated (linkedin, indeed, glassdoor) with manual CAPTCHA gate. **New in this upgrade:** `sources/exceptions.py` provides typed fetch errors; `fetcher.classify_response()` maps HTTP responses to `SourceStatus`; adapters may raise the typed exceptions (runner maps them to statuses).

---

## 8. VERIFICATION & AUTHENTICITY (`verify.py`)

**CLOSED short-circuits (no network):** empty/MISSING URL, `validThrough` in the past — both also set `decision = REJECT`.

**Network checks:** GET 20s, `follow_redirects=True`; 404/410/5xx → CLOSED; final URL stored back; 8KB snippet scanned against `CLOSED_MARKERS`; `blocked_response` (403/429/CAPTCHA) → `verified_reachable` missing + score capped 40. A `_verify_ctx` dict is attached (status_code, redirect_to, blocked, closed_marker, position_filled, captcha) for the evidence builders.

**Confidence score (0-100)** — semantics unchanged (backward compat), internals now sourced from `algo.authenticity_features`:

| Component | Weight |
|---|---|
| Field completeness (6 fields) | +8 each (max 48) |
| Freshness: fresh/recent/older/stale | +24/+16/+4/-10 |
| ATS-boost sources | +10 |
| `validThrough` expired | -20 |
| *Base cap* | **80** |
| Employer-domain match | +25 (to 100) |
| Domain mismatch | capped at **55** |

**Authenticity score (0-100)** — separate weighted raw heuristic (`scoring/authenticity.py`): `5×source_authority + 15×domain_match + 5×posting_id + 15×http_status + 5×validThrough + 10×freshness + 10×completeness + 10×cross_source − 15×closed_markers`. **Explicitly a raw heuristic, never called "probability"** (calibration is Phase-4 gated).

---

## 9. DEDUPE & STATE (`dedupe.py`) — SQLite v3

- **Schema v3** (`schema_meta.version=3`): v2 + 18 columns — `canonical_job_id`, `block_key`, `possible_duplicate_of`, `identity_score`, `authenticity_score`, `match_score`, `decision`, `matched_via DEFAULT 'exact'`, `original_url`, `canonical_url`, `final_url`, `description_fingerprint`, `job_version DEFAULT 1`, `posting_id`, `source_authority`, `evidence`, `negative_evidence`, and `description` (needed for cross-run description similarity). Indexes on `block_key`, `canonical_job_id`, `possible_duplicate_of`.
- **Migration** — idempotent: v1 placeholder table → full v3 rebuild; existing v1/v2 tables get guarded `ALTER TABLE ADD COLUMN`. Verified against a copy of the live DB: 24 rows preserved, version → 3.
- **`upsert(job)`** — unchanged signature/return (`bool genuinely_new`); now stores all v3 columns; repeat sight merges `seen_sources` and refreshes mutable fields.
- **`find_candidates(job, limit=25)`** — lookup order: exact `job_id_hash` → `canonical_job_id` → `canonical_url`/`posting_id` → rows matching any block key (`LIKE '%;key;%'` against the `;`-delimited column), LIMIT-bounded.
- **`fuzzy_lookup(job)`** — composite similarity vs candidates: `auto_merge` (HIGH) → `matched=True`, `matched_via="fuzzy"`, `decision_hint="AUTO_ACCEPT"`; `review` (MEDIUM) → `possible_duplicate_of` + REVIEW hint; `none` → no match.
- **`merge(job, existing_row)`** — refresh `last_seen_at`/`seen_sources`/mutable fields; does NOT set `genuinely_new` and never inserts.
- **Retention:** CLOSED rows pruned after 90 days on open.
- **Live DB state (verified):** `jobs.db` = 24 rows, all `AUTHENTIC`, schema **v3** after auto-migration.

---

## 10. ALGORITHMS & SCORING

### `algo.py` — single source of truth (pure stdlib; rapidfuzz only as guarded accelerator)
- **Jaro-Winkler** with `match_distance = max(0, max(len1,len2)//2 - 1)` (short-string safe).
- **Token shingle Jaccard** (exact, not MinHash) for description similarity; missing descriptions are neutral (0.5), never evidence.
- **`company_similarity`** `= 0.45·C_name + 0.35·C_domain + 0.20·C_url` with rule table: high name + matching domain → strong (≥0.95); high name + conflicting domain → capped ≤0.55; unknown domain → uncertain. A single differing char never decides identity.
- **`composite_similarity`** `S = 0.35·S_title + 0.25·S_company + 0.15·S_location + 0.25·S_desc` with verdicts: `none` if `S_title < TITLE_FLOOR (0.75)`; `auto_merge` if `S ≥ HIGH_THRESHOLD (0.88)` AND company identity pass AND no domain contradiction; `review` if `S ≥ REVIEW_THRESHOLD (0.80)`; else `none`.
- **Blocking keys (5):** company+title-stem, company+location-bucket, domain+title-stem, external posting id, apply-domain+title-stem — empty components omitted.
- **BM25** (`k1=1.5, b=0.75`) pure Python with optional idf map; used by relevance scoring.
- **`authenticity_features(job)`** — the 9-feature vector consumed by verify and (Phase-4 gated) logistic regression.

### `scoring/matching.py` — relevance
`score_match = 0.60·(0.60·BM25(title) + 0.40·BM25(desc)) + 0.20·skill_overlap + 0.10·experience + 0.10·location`, all components 0-1. `skill_normalize` synonym map (py→python, node→nodejs, k8s→kubernetes, c++→cpp…). Hard matcher rules run first and cannot be overridden.

### `scoring/decision.py` + `thresholds.py` — centralized thresholds
`AUTO_ACCEPT_IDENTITY=0.95` (or no-candidates/0.0 = "no known duplicates"), `AUTO_ACCEPT_AUTHENTICITY=70`, `AUTO_ACCEPT_MATCH=0.60`, `REVIEW_MATCH=0.40`, medium-authenticity 40, uncertain-identity floor 0.60. `decide(identity, authenticity, match, state)`: CLOSED/excluded/invalid-URL → `REJECT`; all three high → `AUTO_ACCEPT`; medium relevance OR uncertain identity OR medium authenticity → `REVIEW`; else `REJECT`. Decision reasons are appended to the job's reason list.

---

## 11. REPORTS & NOTIFICATION

**Reports** (`reports/<ts>/`): Jinja2 HTML (autoescape on) with a **Decision column** + top reason; CSV now **34 columns** (adds decision, identity/authenticity/match scores, `matched_via`, `possible_duplicate_of`, `canonical_job_id`, `block_key`, `evidence`, `negative_evidence`, `reason`); JSON full `asdict` dump.

**Live run (2026-08-21 04:20, `reports/20260821-042027/`):** remoteok fetched 100 raw, 1 matched ("Senior Software Engineer Case Execution" @ Pivotal Health) — `decision=REVIEW`, `identity_score=1.0` (exact duplicate of a stored row, `matched_via=exact`), `authenticity_score=42`, `match_score=0.57`, reasons `[application is active, recently posted, relevance medium, authenticity medium]`. **0 genuinely new** — cross-run dedup correctly suppressed the repeat.

**Telegram** (`notify/telegram.py`): HTML parse mode with escaping on all fields; card now shows **Decision + top reason**; **push gate = `decision == AUTO_ACCEPT` AND `genuinely_new` AND not CLOSED** (was `confidence_score >= 50`). Fuzzy-merged (HIGH) and REVIEW jobs never alert — conservative by design. CSV attachment still sent every run.

---

## 12. PHASE 4 EVALUATION (GATED — `jobharness/evaluation/`)

- **`dataset.py`** — JSONL labeled-pair format `{a, b, label, notes}`; deterministic generator (seed 42) synthesizes ~200 pairs: positive = title rewords / company aliases / location variants / description rewordings; negative = distinct jobs.
- **`metrics.py`** — precision/recall/F1, duplicate PRF at thresholds, expected calibration error (ECE).
- **`calibration.py`** — pure-Python Platt scaling (gradient descent), no scikit-learn needed.
- **`fellegi_sunter.py`** — m/u estimates + log2 agreement/disagreement weights, HIGH/MIDDLE/LOW bands. **Experiment module only.**
- **`benchmark.py`** — `python -m jobharness.evaluation.benchmark` prints a metrics table for dedup, authenticity, matching (ran clean; dedup precision 1.0 at threshold 0.88, authenticity/matching F1 1.0 on the synthetic set).
- **GATE:** production wiring is behind `profile.use_ml: false` (default); `pyproject.toml` gains optional extra `ml = ["scikit-learn>=1.4", "numpy>=1.26"]`. Nothing calls unvalidated probabilities in production. No 99%-precision claim is made until an independently labeled dataset exists.

---

## 13. TEST SUITE — `166 passed in ~3.2s`

Coverage map (27 files; 91 tests added in this upgrade):

| Area | Files |
|---|---|
| Algorithms (JW edge cases, composite verdicts, company rule table, blocking keys, BM25, features, fingerprint) | `test_algo` |
| URL canonicalization (utm/tracking strip, idempotence, domain) | `test_urlutil` |
| Dedupe v3 (v2→v3 migration, v1 rebuild, upsert new columns, fuzzy HIGH/MEDIUM/LOW, merge) | `test_dedupe_v3` |
| Identity (posting IDs per source, company aliases, location buckets, title) | `test_identity` |
| Evidence (signals, reasons, source authority, authenticity score range, status enum) | `test_evidence` |
| Source statuses (classify_response, runner mapping incl. typed exceptions, empty, no_match) | `test_source_status` |
| Matching (BM25 ranking, synonyms, exclusion override, location/seniority) | `test_matching` |
| Decision matrix (boundaries, hard states, no-candidates auto-accept) | `test_decision` |
| Evaluation (dataset counts/round-trip, metrics, calibration, Fellegi-Sunter) | `test_evaluation` |
| Original 75 (extraction, freshness, matcher, verify, dedupe, runner E2E, adapters, JSON-LD, reports, telegram) | 18 files |

All offline — network mocked or fixture-driven.

---

## 14. OBSERVATIONS, RISKS & RECOMMENDATIONS

**Strengths**
- "Never fabricate" invariant enforced at prompt, extractor, parser, verifier layers.
- Deterministic-before-probabilistic identity: exact keys (hash/canonical id/URL/posting id) first, blocking + composite similarity second, Fellegi-Sunter/Platt only as gated experiments.
- Single implementation rule: `algo.py` is the only home for algorithms; `urlutil` the only home for URL/domain logic; `scoring/thresholds.py` the only home for thresholds.
- Conservative push gate (`AUTO_ACCEPT` only) — fewer alerts, documented behavior.
- Additive architecture: zero hard deps added; all 75 legacy tests untouched and green.

**Risks / gaps (honest)**
1. **Thresholds are untuned heuristics** — TITLE_FLOOR/HIGH/REVIEW and the decision thresholds are starting points; Phase 4 labeled data + benchmark must validate/tune them before they're trusted at scale.
2. **Fuzzy merge needs descriptions** — cross-run HIGH merges rely on stored `description`; pre-v3 rows (NULL description) fall back to neutral desc similarity → conservative REVIEW instead of merge (safe, but re-alerts possible for title-rewritten repeats).
3. **Backend vs Frontend discrimination** — Jaro-Winkler alone scores them 0.79 (above the 0.75 title floor); separation relies on description similarity, so identical boilerplate descriptions across genuinely different roles remain a boundary risk to validate with the labeled dataset.
4. **Fewer Telegram alerts** — REVIEW-heavy aggregator jobs (authority 2 → authenticity ~40s) rarely reach AUTO_ACCEPT; intentional, but users should expect quieter push.
5. **`my-target.yaml` / `.kilo/` untracked** — intentional; keep them out of commits.
6. **Windows-only note** — `browser.py` chmod is a no-op on win32; CAPTCHA gate blocks the CLI thread on `input()` (expected for the headed workflow).
7. **No lint/typecheck config** — no ruff/mypy in `pyproject.toml`; only pytest (plan: add only if requested).
8. **All keys empty in `.env`** — LLM extraction + Telegram push dormant until secrets are configured.

**Suggested next steps**
- Collect an independently labeled duplicate dataset from real reports; extend `evaluation/dataset.py`; run `python -m jobharness.evaluation.benchmark` to tune thresholds.
- Consider filling `description` backfill for pre-v3 rows from `reports/*/report.json` on migration.
- Add ruff/mypy to the `dev` extra.
- Populate/remove `RawJob.raw_html`; surface LLM extraction warnings.
- `--since`/incremental mode + scheduler wrapper for true automation.

---

*Report compiled from live repository state, full source read, DB inspection (v3 migration verified on a copy), a fresh `pytest` run (166 passed), and a live harvest run (remoteok, 100 raw → 1 matched, 0 new). All facts verified as of 2026-08-21 04:22 IST.*
