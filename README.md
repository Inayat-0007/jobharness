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
  from the Telegram push (still listed in the report).

## Output

Per run, under `reports/<timestamp>/`:
- `report.html` — readable table with Apply buttons
- `report.csv` — flat spreadsheet
- `report.json` — full structured data

Telegram (if configured) sends one card per genuinely-new, authentic job with a
direct Apply button, plus the full CSV attached.

State: `jobs.db` (SQLite) stores `job_id_hash = sha1(normalize(title|company|location))`
so reposts across sources collapse into one row; `first_seen_at` flags which
are genuinely new this run.

## Secrets & security

All keys live in `.env` (gitignored, never committed). Required for full run;
the harness degrades gracefully when a key is absent (that source is skipped).

## Tests

```powershell
python -m pip install pytest
python -m pytest tests\ -q
```

28 offline tests cover: no-hallucination extraction, RemoteOK parsing, dedupe,
verifier CLOSED detection, matcher filters, report generation, and the full
end-to-end pipeline (no network needed).

## Honest limitations

- "Genuine/authentic" means the posting page is reachable and fields are
  source-derived — it cannot prove the employer's intent. Stated up front.
- LinkedIn/Glassdoor ToS: scraping risks account ban; use a secondary account
  with the gated sources. Documented, not enforced.
- Google for Jobs and gated sources are detection-prone; a run may return fewer
  results on a given day. The harness never fabricates to fill the gap.
