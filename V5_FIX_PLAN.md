# V5 Fix Plan — "real data, no repeats, Excel delivery"

Scan target: branch `v4` @ `2df1a18` + uncommitted working-tree changes (the most recent version).
Scan date: 2026-08-22. Evidence: `logs/jobharness.log`, `reports/20260822-064606/manifest.json`.

---

## 1. Scan findings (root causes)

### F1. Every LLM extraction call fails — the #1 data-quality bug
Last run: `LLM usage: 240 calls, 0 ok, 0 rate-limited`.

- Active profile (`profiles/my-target-live.yaml`) sets `llm_provider: nvidia`.
- NVIDIA endpoint **times out** on every call (`The read operation timed out`, 60s each).
- DeepSeek direct key returns **402 Payment Required** (out of credit).
- Gemini / GLM / Qwen / OpenRouter have no (working) keys.
- The circuit breaker only cools down on **HTTP 429**. Timeouts and 402s reset the
  failure counter, so the broken provider is re-tried on *every* call.
  Result: the extract stage burned **1230s of the 1389s run** on dead calls.

Effect: extraction silently falls back to raw fields. Salaries, experience ranges,
posting dates and seniority stay un-normalized → weaker matching, weaker dedupe
linkage, and "same old" looking output.

### F2. Reports look repeated because they contain ALL matched jobs
Telegram correctly pushes only genuinely-new jobs (7 last run), but the attached
file contains all 64 matched jobs including ones seen days ago. So every file
looks "mostly repeated" even when dedupe is working.

### F3. Verification re-fetches every apply URL on every run
No verify cache. LinkedIn apply URLs are re-requested each run → hundreds of
`429 Too Many Requests` in the log → jobs marked DEGRADED → pushed with an
"unverified" warning, again and again for the same URLs.

### F4. Telegram attachment is a Playwright-rendered PDF
User wants a **well-designed Excel workbook** with complete fields, shortened
hyperlinks, and wrapped text.

---

## 2. Fix plan

### Phase A — LLM providers: one free-trial DashScope key, 4 models (fixes F1)
Alibaba Cloud Model Studio (DashScope international) exposes an
OpenAI-compatible endpoint and the free-trial key serves all target models:

| provider id          | model              | role                                   |
|----------------------|--------------------|----------------------------------------|
| `dashscope_qwen`     | `qwen3.8-max`      | primary extractor                      |
| `dashscope_deepseek` | `deepseek-v4-flash`| fast fallback                          |
| `dashscope_glm`      | `glm-5.2`          | fallback                               |
| `dashscope_pro`      | `deepseek-v4-pro`  | deep fallback                          |

Endpoint: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
(verified live: `/models` lists all four models for this key).

**Quota status (verified 2026-08-22 with key `qwenalibaba-inayat`):**
- `deepseek-v4-flash` — **live**, returns grounded JSON extraction. Serves as
  the workhorse of the chain.
- `deepseek-v4-pro` — live (heavy reasoning; deep fallback).
- `qwen3.8-max` / `glm-5.2` — HTTP 403 `AllocationQuota.FreeTierOnly` on this
  key (free quota exhausted). They stay first in the chain; the new quota
  **quarantine** (24h on a single 403-quota error) skips them after one
  attempt. When the other free-trial keys arrive, drop them into
  `DASHSCOPE_QWEN_API_KEY` / `DASHSCOPE_GLM_API_KEY` — the per-model key
  override picks them up with zero code changes.

**Reasoning-model fix (found during live validation):** the DashScope
deepseek-v4 models emit `reasoning_content` BEFORE the answer. With the old
`max_tokens=900` cap the whole budget was consumed by reasoning
(`finish_reason=length`, empty `content`) — so all 80 "ok" calls returned
nothing and the consistency gate had nothing to adopt. `complete()` now
defaults to **max_tokens=4000**, which leaves room for reasoning + the JSON
answer (verified: `finish=stop`, content populated).

**Adzuna adapter bug (found during live validation):** the API field is
`company.display_name` (underscore) but the adapter read `displayname` →
company was empty for every Adzuna job. Fixed with both spellings; salary
min/max are now formatted as a range (`600000 - 900000`) instead of a bare
number.

Changes in `jobharness/llm/provider.py`:
- Add the four `dashscope_*` provider entries (shared `DASHSCOPE_API_KEY`,
  per-model override via `DASHSCOPE_<MODEL>_API_KEY`).
- New fallback chain: dashscope_qwen → dashscope_deepseek → dashscope_glm →
  dashscope_pro → deepseek → nvidia → openrouter → gemini → glm → qwen.
- **Circuit breaker upgrade**: any 3 consecutive failures (429, timeout,
  402, 5xx, network) cool the provider for 300s — not just 429s. Dead
  providers are skipped instead of burning 60s per call.
- **Quota quarantine**: a single `AllocationQuota` error (e.g. free-tier
  exhausted) cools the provider for 24h — it cannot recover mid-run.
- Client timeout split: connect 10s / read 45s.

Config: `.env` gets `DASHSCOPE_API_KEY` (+ model envs); `.env.example`
documents everything without secrets. Profile switches to `dashscope_qwen`.

### Phase B — Verify cache (fixes F3)
New `jobharness/verify_cache.py`: SQLite-backed cache (in `jobs.db`) keyed by
apply URL. Definitive outcomes (reachable-200, CLOSED 404/410/closed-marker)
are cached 24h; DEGRADED/transient outcomes are never cached.
- Stop hammering LinkedIn (no more 429 storms on known URLs).
- Repeat runs become fast and only truly-new URLs are checked.
- Thread-safe (lock + `check_same_thread=False`), best-effort (cache failure
  never fails verification).

### Phase C — Designed Excel report replaces PDF on Telegram (fixes F2, F4)
New `write_xlsx()` in `jobharness/report.py` (openpyxl, added to dependencies):

- **Summary sheet**: run timestamp, totals (new/closed/degraded), LLM model
  chain, per-source status — styled title block.
- **Jobs sheet** (one row per job, newest first):
  - complete field set — no gaps: fresh flag, posted date, title, role,
    company, location, remote, experience, salary, seniority, tech stack,
    match/authenticity/confidence scores, decision + reason, status, NEW flag,
    sources, employer domain, posting id, apply link, missing fields,
    first-seen;
  - **shortened hyperlinks**: Apply cell shows `apply ▸ acme.com/…` (display
    text capped ~40 chars) with the real hyperlink attached; the full URL
    lives in its own column;
  - **design**: dark-blue header with white bold text, freeze panes +
    auto-filter, zebra striping, decision color coding (green AUTO_ACCEPT,
    amber REVIEW, red REJECT), NEW rows highlighted, wrapped long text,
    tuned column widths, borders.
- Runner builds the workbook and Telegram sends the **XLSX**; PDF stays as a
  local artifact only.

### Phase D — Fresh-data guarantees
- Sources already favor freshness (adzuna `max_days_old=7&sort_by=date`,
  linkedin_guest `f_TPR=r86400&sortBy=DD`) — kept.
- With the LLM fixed, date normalization and grounded extraction restore real
  per-job detail, so matched output changes day-to-day instead of repeating
  the same degraded rows.
- `--since N` incremental mode remains available; Telegram push stays
  genuinely-new-only.

### Phase E — Verification
- Unit tests: dashscope provider defaults + fallback order, all-failure
  cooldown, xlsx writer (sheets, hyperlinks, wrap), verify cache hit/miss/TTL.
- Full suite: `pytest`, `ruff check`, `mypy`.
- **Live run**: real harvest with the new key — expect `LLM usage ok > 0`,
  new count > 0, and the XLSX delivered to Telegram (200 on sendDocument).

---

## 3. Risk notes

- Dead providers (nvidia/openrouter/direct-deepseek) remain configured as
  late fallbacks; the upgraded breaker prevents them from slowing runs.
- If two more free-trial keys arrive later, they plug into the existing env
  slots (`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`) with no
  code change.
- The DashScope key and all secrets live only in `.env` (gitignored).
