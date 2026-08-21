from __future__ import annotations

import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..base import SourceAdapter
from ...models import RawJob
from ...profile import Profile
from ...browser import open_browser
from ...fetcher import make_client, random_delay
from ..jobposting_ld import extract_jobpostings_from_html


JOB_HREF_RE = re.compile(r"/(job|jobs|position|positions|requisition|opening|vacancy)/", re.I)
NAV_TEXTS = (
    "all jobs", "search jobs", "view all", "job alerts", "careers home", "job search",
    "find jobs", "browse jobs", "how to apply", "recommended jobs", "saved jobs",
    "login", "register", "sign in", "sign up", "contact", "about us", "faq",
    "learn more", "know more", "read more", "view details", "latest vacancies",
    "access zoho home", "apply now",
)
LOC_HINT_RE = re.compile(
    r"(india|bangalore|bengaluru|hyderabad|pune|mumbai|chennai|delhi|gurgaon|gurugram|"
    r"noida|kolkata|remote|united states|united kingdom|singapore|germany|japan)",
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_SPACE_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    text = _SCRIPT_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


class CareerPageBrowserAdapter(SourceAdapter):
    """Scrape employer career pages in parallel headless browsers.

    Modern career sites (Microsoft, Amazon, Flipkart, ...) are JS-rendered apps
    with NO JSON-LD in the listing DOM. This adapter renders each page in a
    stealth headless Chromium, extracts job cards from the rendered DOM
    (anchors pointing at job-detail URLs), then enriches each card by fetching
    its detail page with plain HTTP - full descriptions come from the detail
    page's JSON-LD JobPosting block, or a text fallback. Titles, locations and
    apply URLs come from the rendered page (never invented).

    Sites are visited in parallel (4 headless contexts) with live progress
    lines, so a run never looks stalled. Headless is safe: career pages are
    public job boards, no login and no CAPTCHA. Only the first page of each
    career site is scraped (no pagination).
    """

    name = "career_page_browser"
    _workers = 4
    _detail_cap = 15

    def fetch(self, profile: Profile) -> list[RawJob]:
        seeds = []
        for c in profile.career_pages or []:
            if isinstance(c, dict):
                u = c.get("url")
                company = c.get("company", "")
            elif isinstance(c, str):
                u = str(c)
                company = ""
            else:
                continue
            if u:
                seeds.append((company, u))
        if not seeds:
            return []
        workers = min(self._workers, len(seeds))
        chunks = [seeds[i::workers] for i in range(workers)]
        out: list[RawJob] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(self._visit_chunk, i, chunk) for i, chunk in enumerate(chunks)]
            for fut in as_completed(futs):
                try:
                    out.extend(fut.result())
                except Exception:
                    continue
        print(f"[{self.name}] done: {len(out)} jobs from {len(seeds)} career pages")
        return out

    def _visit_chunk(self, worker: int, chunk: list) -> list:
        out: list[RawJob] = []
        with open_browser(
            f"career_{worker}",
            headless=True,
            use_real_profile=False,
            timezone_id="Asia/Kolkata",
            locale="en-IN",
            serialize=False,
        ) as (_p, browser):
            page = browser.pages[0] if browser.pages else browser.new_page()
            total = len(chunk)
            for i, (company, seed) in enumerate(chunk, start=1):
                print(f"[{self.name}] [{i}/{total}] {company or seed}")
                time.sleep(random.uniform(0.5, 1.5))
                try:
                    page.goto(seed, timeout=25000, wait_until="domcontentloaded")
                except Exception:
                    continue
                time.sleep(3.5)
                try:
                    html = page.content()
                except Exception:
                    continue
                jobs = []
                try:
                    jobs = extract_jobpostings_from_html(html, self.name, seed, company)
                except Exception:
                    jobs = []
                if not jobs:
                    jobs = self._extract_anchors(page, seed, company)
                if jobs:
                    self._enrich(jobs[: self._detail_cap])
                    print(f"[{self.name}] {company or seed}: {len(jobs)} jobs")
                out.extend(jobs)
        return out

    def _extract_anchors(self, page, seed: str, company: str) -> list:
        try:
            links = page.evaluate(
                "Array.from(document.querySelectorAll('a')).map(a => ({href: a.href, "
                "text: (a.innerText || '').trim()})).filter(l => l.href && l.text)"
            )
        except Exception:
            return []
        out: list[RawJob] = []
        seen: set = set()
        for link in links:
            href = link.get("href") or ""
            text = link.get("text") or ""
            if not href or not JOB_HREF_RE.search(href) or href in seen:
                continue
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if not lines:
                continue
            title = lines[0]
            low = title.lower()
            if len(title) < 8 or low in NAV_TEXTS or any(n in low for n in NAV_TEXTS):
                continue
            location = ""
            for ln in lines[1:]:
                if len(ln) > 60:
                    continue
                if "," in ln or LOC_HINT_RE.search(ln):
                    location = ln
                    break
            seen.add(href)
            out.append(
                RawJob(
                    source_name=self.name,
                    source_url=href,
                    title=title,
                    company=company or "",
                    location=location,
                    description="",
                    apply_url=href,
                )
            )
            if len(out) >= 50:
                break
        return out

    def _enrich(self, jobs: list) -> list:
        """Fetch each job's detail page; description/location/date from JSON-LD
        JobPosting, or a stripped-text fallback. Parallel, rate-limited."""

        def _one(job: RawJob) -> None:
            random_delay()
            try:
                with make_client(timeout=20.0) as client:
                    resp = client.get(job.apply_url or job.source_url)
            except Exception:
                return
            if resp.status_code != 200:
                return
            try:
                ld = extract_jobpostings_from_html(resp.text, self.name, resp.url or "", job.company or "")
            except Exception:
                ld = []
            if ld:
                j = ld[0]
                if not job.description and j.description:
                    job.description = j.description
                if not job.location and j.location:
                    job.location = j.location
                if not job.posted_date and j.posted_date:
                    job.posted_date = j.posted_date
            elif not job.description:
                job.description = _strip_html(resp.text)[:4000]

        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(_one, j) for j in jobs]
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception:
                    pass
        return jobs
