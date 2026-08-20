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

## Authenticity & confidence scoring

Each job gets a `confidence_score` (0-100) computed from:
- field completeness (title/company/url/date/location/experience),
- freshness (`fresh` > `recent` > `older` > `stale`),
- employer-domain match — the resolved apply URL host is checked against the
  company name; aggregator-only URLs (e.g. `remoteok.com` for "Pivotal Health")
  are capped lower because the apply link is not the employer's ATS,
- employer ATS sources (Greenhouse/Lever/career pages/USAJobs) get a boost.

Telegram only pushes jobs with `confidence_score >= 50`, so weak/aggregator-only
leads stay in the report but don't spam your phone.

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
- `report.html` — readable table with Apply buttons + Score + Status + Domain
- `report.csv` — flat spreadsheet (includes confidence/valid_through/domain)
- `report.json` — full structured data

Telegram (if configured) sends one card per genuinely-new, authentic,
sufficient-confidence job with a direct Apply button, plus the full CSV attached.

State: `jobs.db` (SQLite v2, auto-migrated from v1) stores
`job_id_hash = sha1(normalize(title|company|location))` so reposts across
sources collapse into one row; `first_seen_at` flags which are genuinely new.
CLOSED jobs are pruned after 90 days of inactivity. CLOSED jobs are never
alerted as "new".

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

50 offline tests cover: no-hallucination extraction, RemoteOK parsing, dedupe +
v1→v2 schema migration + retention pruning, verifier CLOSED/confidence/domain
logic, freshness date parsing (RFC-2822/ISO-Z/offset/plain/future), the shared
JobPosting JSON-LD parser, matcher filters, report generation, and the full
end-to-end pipeline (no network needed).

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
