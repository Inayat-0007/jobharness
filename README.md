# Job Harness

On-demand job harvest harness. Run it when you want fresh results: it pulls job
postings across every available channel, extracts structured fields from the
**source content only** (no hallucination / no fabricated data), deduplicates
across sources, verifies the direct apply URL is reachable (not CLOSED), and
delivers an HTML/CSV/JSON report plus Telegram push for genuinely new openings.

## Quick start

```powershell
# 1. Install (editable) + browser engine for gated scrapers
cd C:\Users\moham\jobharness
python -m pip install -e .
python -m playwright install chromium

# 2. Configure secrets (LLM keys, Telegram, optional aggregator/proxy keys)
copy .env.example .env
notepad .env

# 3. Edit your target profile
notepad profiles\demo.yaml

# 4. Run one harvest pass
python -m jobharness run --profile profiles\demo.yaml

# 5. Regenerate the all-runs dashboard (aggregates every report)
python -m jobharness dashboard

# Dry-run (no URL verification, no Telegram push) — fast, offline-safe
python -m jobharness run --source remoteok --top 5 --dry-run --no-llm

# Only specific sources (repeat --source)
python -m jobharness run --source remoteok --source weworkremotely
```

## Profile fields (`profiles/*.yaml`)

| field             | purpose                                                          |
|-------------------|------------------------------------------------------------------|
| `roles`           | target role phrases; job matches if any appears in title/desc     |
| `keywords`        | tech keywords; job matches if ANY is present (OR)                |
| `excludes`        | hard-reject if any term appears                                   |
| `location`        | location filter                                                  |
| `remote`          | prefer remote postings                                           |
| `seniority`       | e.g. `senior`; rejects non-matching seniority when known          |
| `salary_floor`    | minimum salary (number); rejects postings below it when known    |
| `company_allowlist` | list of board slugs (Greenhouse/Lever) or `{company, url}` dicts |
| `sources`         | per-source enable flags (true/false)                             |
| `llm_provider`    | `gemini` / `glm` / `qwen`                                         |
| `top_n`           | max results per source                                            |

## Source tiers

- **Tier 1 — API/RSS (legal, fast):** RemoteOK, WeWorkRemotely, Remotive,
  Jobicy, Adzuna, USAJobs. No login, no bans.
- **Tier 4 — Career pages:** Greenhouse, Lever (board APIs), and a generic
  JSON-LD/`schema.org JobPosting` scraper for any company career URL.
- **Tier 3 — Google for Jobs:** best-effort scrape of JobPosting structured
  data. Detection-prone; degrades to empty rather than fabricating.
- **Tier 5 — Login-gated (LinkedIn, Indeed, Glassdoor):** headed Playwright +
  persistent cookies + stealth + optional proxy. **CAPTCHA is solved by YOU** —
  the run pauses and prints a prompt; solve it in the browser, then press ENTER.
  No automated captcha solving, by design. Enable in profile (off by default).

## Anti-bot defenses

Rotating proxy list (`PROXY_LIST`), realistic headers + UE pool, human-like
jittered delays, persistent login cookies, stealth, tenacity-style retries,
block detection (403/429 + CAPTCHA markers) → log + skip source + continue.

## The "0 fake data" guarantee

- Every extracted field is sourced from parsed HTML/JSON. The LLM is used ONLY
  to extract fields from provided source text, with a prompt that forbids
  invention and forces the literal string `MISSING` for unknown fields.
- Unconfirmed fields are stored as `MISSING`/empty and listed in
  `missing_fields` — never fabricated.
- The verifier follows `apply_url` redirects; if the page is unreachable or
  shows a "no longer accepting" marker, the job is marked `CLOSED` and excluded
  from the Telegram push (still listed in the report). `validThrough` in the past
  also marks `CLOSED` without a network call.

## Authenticity, identity & relevance scoring

Each job carries three scores (all stored as raw heuristics — **not
probabilities** until Phase 4 calibration produces data-backed values):

- `identity_score` (0-1) — how similar this posting is to an already-stored
  one (`algo.composite_similarity`: title Jaro-Winkler + company identity +
  location + description, with hard title-floor and domain-contradiction
  gates). 0.0 = no known duplicate.
- `authenticity_score` (0-100) — weighted raw heuristic from
  `jobharness/scoring/authenticity.py`: source authority, employer-domain
  match, posting ID, HTTP status, validThrough, freshness, completeness,
  cross-source agreement, minus closed markers.
- `match_score` (0-1) — BM25 relevance vs the profile
  (`jobharness/scoring/matching.py`): 0.60 * (0.60*title + 0.40*description)
  blended with 0.20 skill overlap, 0.10 experience, 0.10 location. Hard
  matcher rules (`matches_profile`) stay authoritative — BM25 only ranks.

The decision engine (`jobharness/scoring/decision.py`) maps the three scores
to a per-job `decision` (`AUTO_ACCEPT` / `REVIEW` / `REJECT`); all thresholds
are centralized in `jobharness/scoring/thresholds.py` and `jobharness/algo.py`
— never scattered in runner/verify/matcher.

`confidence_score` remains as a backward-compatible column.

### Push gate

Telegram pushes only `decision == AUTO_ACCEPT` **and** `genuinely_new` **and**
not CLOSED. Fuzzy-merged (HIGH identity) and REVIEW jobs never alert — this is
deliberately conservative: fewer, higher-confidence alerts. Reports still list
everything with a Decision column.

### Source statuses

Each run records a per-source `SourceStatus` (ok / empty / blocked /
rate_limited / auth_required / source_down / parse_failure / no_match),
printed in the summary and returned in the run result.

### Cross-source & cross-run dedup

- Within-run: same title+company collapses to one extraction (unchanged).
- Cross-run: blocking keys (company+title stem, company+location bucket,
  domain+stem, posting ID, apply-domain+stem) find candidates; `fuzzy_lookup`
  scores them — HIGH merges into the stored row (no alert), MEDIUM flags
  `possible_duplicate_of` + REVIEW, LOW follows the normal new path.
- `job_id_hash` stays the primary key; `canonical_job_id` (posting ID →
  canonical URL → company entity + title → company+title+location → hash)
  enables lookup before upsert.

## Anti-bot (gated sources)

Stealth-hardened Playwright: `--disable-blink-features=AutomationControlled`,
realistic UA/locale/timezone, `playwright-stealth` when available (manual
`navigator.webdriver` patch fallback), persistent login cookies per source,
optional rotating proxies, jittered delays, scroll-to-load for lazy cards,
resilient multi-selector fallbacks. On a hard block the scraper automatically
retries with a mobile context; on a CAPTCHA it pauses for you to solve it
manually (no automated solving, by design).

## Output

Per run, under `reports/<timestamp>/`:
- `report.html` — readable table with Apply buttons + Score + Decision +
  Status + Domain
- `report.csv` — flat spreadsheet (includes decision, identity/authenticity/
  match scores, evidence, reasons, canonical ids)
- `report.json` — full structured data

`python -m jobharness dashboard` (or `jobharness dashboard`) regenerates
`reports/dashboard.html` — a single self-contained page (no external
dependencies, works offline) aggregating **all** runs under `reports/`:

- Stat cards: unique jobs (deduped by `job_id_hash`, latest record wins),
  genuinely new, closed, remote, average match, authentic count
- Decision / source / status distribution bars
- Live filters: search, decision, status, source, remote-only, new-only
- Sortable columns; click any row for a detail drawer with every stored field
  (scores, evidence, negative evidence, reasons, missing fields, plain-text
  description, apply/source/canonical links, hashes, block keys, timestamps)

The dashboard is regenerated on demand after each run — no server needed.

Telegram (if configured) sends one card per AUTO_ACCEPT genuinely-new job with
a direct Apply button (card shows decision + top reason), plus the full CSV
attached.

State: `jobs.db` (SQLite v3, auto-migrated from v1/v2) stores
`job_id_hash = sha1(normalize(title|company|location))` so reposts across
sources collapse into one row; `first_seen_at` flags which are genuinely new.
v3 adds identity/authenticity columns (`canonical_job_id`, `block_key`,
`possible_duplicate_of`, scores, decision, `matched_via`, posting ID, evidence,
description) with indexed lookup. CLOSED jobs are pruned after 90 days of
inactivity. CLOSED jobs are never alerted as "new".

## Cost & rate safety

LLM extraction is capped to a per-run budget (`DEFAULT_LLM_BUDGET=200`); once
exceeded, remaining jobs use fast no-LLM extraction. Verify runs concurrently
(throttle 6) to bound wall-clock. Each source degrades gracefully when its key
is absent.

## Secrets & security

All keys live in `.env` (gitignored, never committed). The `cookies/` dir is
gitignored and chmod-restricted where possible. Required for full run; the
harness degrades gracefully when a key is absent (that source is skipped).

## Tests

```powershell
python -m pip install pytest
python -m pytest tests\ -q
```

170 offline tests cover: no-hallucination extraction, RemoteOK parsing, dedupe +
v1→v2→v3 schema migration + retention pruning, verifier CLOSED/confidence/domain
logic, freshness date parsing (RFC-2822/ISO-Z/offset/plain/future), the shared
JobPosting JSON-LD parser, matcher filters, report generation, the all-runs
dashboard builder, full end-to-end pipeline, cross-run fuzzy dedup,
identity/posting-id extraction, evidence signals + source statuses, BM25
matching + decision engine, and the evaluation benchmark dataset + metrics
(no network needed).

## Docs

- `TECHNICAL_REPORT.md` — master technical report: architecture map, full
  pipeline walkthrough, data model, scoring model, dedup v3 schema, evaluation,
  test coverage map, and honest risks/gaps + next steps.

## Honest limitations

- "Genuine/authentic" means the posting page is reachable, fields are
  source-derived, and the apply URL resolves to the employer domain — it
  cannot prove the employer's hiring intent beyond the posting itself.
- LinkedIn/Glassdoor ToS: scraping risks account ban; use a secondary account
  with gated sources. By default these are off in the profile — enable
  `linkedin`/`indeed`/`glassdoor` only when you're at the keyboard to solve any
  CAPTCHA in the headed browser.
- Google for Jobs and gated sources are detection-prone; a run may return fewer
  results on a given day. The harness retries (mobile fallback) and never
  fabricates results to fill the gap.

## Risks & known gaps (honest)

1. **Thresholds are untuned heuristics** — TITLE_FLOOR/HIGH/REVIEW and the
   decision thresholds are starting points; Phase 4 labeled data + benchmark
   must validate/tune them before they're trusted at scale.
2. **Fuzzy merge needs descriptions** — cross-run HIGH merges rely on stored
   `description`; pre-v3 rows (NULL description) fall back to neutral desc
   similarity → conservative REVIEW instead of merge (safe, but re-alerts are
   possible for title-rewritten repeats).
3. **Backend vs Frontend discrimination** — Jaro-Winkler alone scores them
   0.79 (above the 0.75 title floor); separation relies on description
   similarity, so identical boilerplate descriptions across genuinely
   different roles remain a boundary risk to validate with the labeled dataset.
4. **Fewer Telegram alerts** — REVIEW-heavy aggregator jobs (authority 2 →
   authenticity ~40s) rarely reach AUTO_ACCEPT; intentional, but expect quieter
   push.
5. **`profiles/my-target.yaml` / `.kilo/` untracked** — intentional; keep them
   out of commits.
6. **Windows-only note** — `browser.py` chmod is a no-op on win32; the CAPTCHA
   gate blocks the CLI thread on `input()` (expected for the headed workflow).
7. **No lint/typecheck config** — no ruff/mypy in `pyproject.toml`; only
   pytest (plan: add only if requested).
8. **All keys empty in `.env`** — LLM extraction + Telegram push are dormant
   until secrets are configured.

## Suggested next steps

- Collect an independently labeled duplicate dataset from real reports; extend
  `evaluation/dataset.py`; run `python -m jobharness.evaluation.benchmark` to
  tune thresholds.
- Consider a `description` backfill for pre-v3 rows from
  `reports/*/report.json` on migration.
- Add ruff/mypy to the `dev` extra.
- Populate/remove `RawJob.raw_html`; surface LLM extraction warnings.
- `--since`/incremental mode + scheduler wrapper for true automation.
- Dashboard polish: export filtered view to CSV, per-run comparison chart,
  light/dark theme toggle.

## Optional extras

```powershell
# Phase 4 ML evaluation (scikit-learn / numpy — not needed for production)
pip install jobharness[ml]
```

## Honest limitations

- "Genuine/authentic" means the posting page is reachable, fields are
  source-derived, and the apply URL resolves to the employer domain — it
  cannot prove the employer's hiring intent beyond the posting itself.
- LinkedIn/Glassdoor ToS: scraping risks account ban; use a secondary account
  with gated sources. By default these are off in the profile — enable
  `linkedin`/`indeed`/`glassdoor` only when you're at the keyboard to solve any
  CAPTCHA in the headed browser.
- Google for Jobs and gated sources are detection-prone; a run may return fewer
  results on a given day. The harness retries (mobile fallback) and never
  fabricates results to fill the gap.
