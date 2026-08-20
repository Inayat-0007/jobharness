# Setup Guide — Everything You Need To Run This

## TL;DR

```powershell
cd C:\Users\moham\jobharness
python -m jobharness run --profile profiles\free-only.yaml --no-llm --no-push
```

**This works RIGHT NOW with zero setup.** It fetches from RemoteOK, WeWorkRemotely,
Remotive, Greenhouse (Airbnb, Stripe), and Lever — all free sources needing no API
keys. The `--no-llm` flag skips AI extraction (uses raw fields); `--no-push` skips
Telegram. You get an HTML/CSV/JSON report in `reports/<timestamp>/`.

---

## What Works Without Any Keys (right now)

| Source        | Type     | Status | Notes                              |
|---------------|----------|--------|------------------------------------|
| RemoteOK      | API      | WORKS  | 100+ jobs per fetch                |
| WeWorkRemotely| RSS      | WORKS  | 260+ jobs across categories        |
| Remotive      | RSS      | WORKS  | 19+ jobs                           |
| Greenhouse    | ATS API  | WORKS  | 761+ jobs (Airbnb, Stripe boards)  |
| Lever         | ATS API  | WORKS  | Add company board slugs to allowlist |

Run these immediately with the `free-only` profile:

```powershell
python -m jobharness run --profile profiles\free-only.yaml --no-llm --no-push
```

---

## Step 1: LLM Provider Key (for better field extraction)

The LLM is **optional** — it improves experience/seniority/salary extraction accuracy.
Without it, the harness still works but those fields may be empty/`MISSING`.

You said you have keys for Gemini, GLM, and Qwen. Get the cheapest one running:

### Option A: Gemini 2.0 Flash (recommended — has a free tier)

1. Go to https://aistudio.google.com/apikey
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the key (starts with `AIza...`)
5. Edit `C:\Users\moham\jobharness\.env`:
   ```
   GEMINI_API_KEY=AIza...your-key-here...
   ```
6. Test it:
   ```powershell
   python -m jobharness run --profile profiles\free-only.yaml --no-push
   ```
   (remove `--no-llm` to enable AI extraction)

### Option B: GLM 4 Flash (Z.ai / Zhipu)

1. Go to https://open.bigmodel.cn/usercenter/apikeys
2. Create a key
3. Set in `.env`:
   ```
   GLM_API_KEY=your-key
   ```
4. Set `llm_provider: glm` in your profile YAML

### Option C: Qwen (DashScope)

1. Go to https://dashscope.console.aliyun.com/apiKey
2. Create a key
3. Set in `.env`:
   ```
   QWEN_API_KEY=your-key
   ```
4. Set `llm_provider: qwen` in your profile YAML

The harness tries the configured provider first, then falls back through the
others automatically. So if Gemini fails, it tries GLM, then Qwen.

---

## Step 2: Telegram Bot Setup (for phone push notifications)

This is how you get instant alerts on your phone when new genuine jobs appear.

### 2a. Create the bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Give it a name (e.g. "Job Harness Bot")
4. Give it a username ending in `bot` (e.g. `myjobharness_bot`)
5. BotFather gives you a **token** like `7123456789:AAH...` — copy it
6. Set in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAH...your-token...
   ```

### 2b. Get your Chat ID

1. Send any message to your new bot in Telegram (say "hi")
2. Open this URL in your browser (replace TOKEN):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":XXXXXXXXX"` in the JSON response — that number is your chat ID
4. Set in `.env`:
   ```
   TELEGRAM_CHAT_ID=XXXXXXXXX
   ```

### 2c. Test it

```powershell
python -m jobharness run --profile profiles\free-only.yaml
```
(remove `--no-push`). You'll get a Telegram card for each genuinely-new job with a
direct Apply button, plus a CSV attachment.

---

## Step 3: Optional API Keys (broader coverage)

### Adzuna (job aggregator API)

1. Go to https://developer.adzuna.com/ (signup is free)
2. Create an app → get App ID and App Key
3. Set in `.env`:
   ```
   ADZUNA_APP_ID=your-id
   ADZUNA_APP_KEY=your-key
   ```
4. Enable in profile: `adzuna: true`

### USAJobs (US government jobs API)

1. Go to https://developer.usajobs.gov/APIRequest/Index
2. Request an API key (free, instant)
3. Set in `.env`:
   ```
   USAJOBS_API_KEY=your-key
   ```
4. Enable in profile: `usajobs: true`

---

## Step 4: Configure Your Target Job Profile

Edit `profiles\demo.yaml` (or make a copy):

```yaml
# The most important fields — set these to YOUR target:
name: my-job
roles:                          # your target job titles
  - Senior Backend Engineer
  - Python Developer
keywords:                       # tech you want (ANY match = keep)
  - python
  - django
  - api
excludes:                       # reject if any appears in title/desc
  - manager
  - frontend
  - react
location: ""                    # empty = anywhere; or "London" / "New York"
remote: true                    # prefer remote postings
seniority: "senior"             # "junior" / "mid" / "senior" (optional)
salary_floor: 80000             # reject below this if salary known (optional)

# Career page boards to monitor (Greenhouse/Lever board slugs):
company_allowlist:
  - airbnb                     # Greenhouse board slug
  - stripe                     # Greenhouse/Lever board slug
  - github                     # Lever board slug

# Which sources to enable:
sources:
  remoteok: true
  weworkremotely: true
  remotive: true
  greenhouse: true
  lever: true
  # These need API keys (Step 3):
  adzuna: true
  usajobs: true
  # These need Playwright + manual CAPTCHA solving (Step 5):
  linkedin: false
  indeed: false
  glassdoor: false

llm_provider: gemini            # gemini / glm / qwen
top_n: 50                       # max results per source
```

Then run:
```powershell
python -m jobharness run --profile profiles\demo.yaml
```

---

## Step 5: Gated Sources (LinkedIn / Indeed / Glassdoor) — OPTIONAL

These open a **real browser window** on your screen. If a CAPTCHA appears, the run
**pauses** and waits for YOU to solve it manually, then continues. By default these
are OFF. To enable:

```yaml
sources:
  linkedin: true
  indeed: true
  glassdoor: true
```

Then run and be ready to solve CAPTCHAs when the browser pops up:
```powershell
python -m jobharness run --profile profiles\demo.yaml --source linkedin
```

**Tips:**
- The first run opens a browser — log into LinkedIn/Indeed manually; cookies persist
  for future runs (stored in `cookies/linkined.json`, gitignored)
- Use a secondary account; scraping risks account bans (against their ToS)
- Run these when you're at the keyboard, not unattended

---

## Step 6: Proxies (optional, for blocked sources)

If your IP gets blocked by a source, add rotating proxies to `.env`:
```
PROXY_LIST=http://user:pass@proxy1.com:8080,socks5://user:pass@proxy2.com:1080
```
The harness rotates through them per request.

---

## Quick Reference: Run Commands

```powershell
# Free run — no keys needed, no phone push, no AI
python -m jobharness run --profile profiles\free-only.yaml --no-llm --no-push

# Full run — with AI extraction + Telegram push (needs keys)
python -m jobharness run --profile profiles\demo.yaml

# Fast dry-run — skip verification + push, just fetch + filter
python -m jobharness run --profile profiles\demo.yaml --dry-run

# Single source test
python -m jobharness run --profile profiles\demo.yaml --source remoteok --no-push

# Run tests
python -m pytest tests\ -q
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Telegram not configured" | Set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` |
| "0 matched" | Your `excludes` or `keywords` are too strict; relax them |
| "provider not configured" | LLM key missing in `.env`; add it or run with `--no-llm` |
| Source returns 0 | Source may be blocking your IP; add a `PROXY_LIST` or try later |
| Browser doesn't appear | Run `python -m playwright install chromium` |
| Greenhouse/Lever: 0 jobs | Add real company board slugs to `company_allowlist` in profile |
