from __future__ import annotations

import html as _html
import time

import httpx

from .. import secrets
from ..models import Job

_client: httpx.Client | None = None
_file_client: httpx.Client | None = None

push_stats = {"sent": 0, "failed": 0}

_RETRY_AFTER_FALLBACK = 2.0
_BATCH_SIZE = 10
_MAX_TEXT_LEN = 1024


def _bot_token() -> str:
    return secrets.get("TELEGRAM_BOT_TOKEN", "")


def _chat_id() -> str:
    return secrets.get("TELEGRAM_CHAT_ID", "")


def configured() -> bool:
    return bool(_bot_token() and _chat_id())


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0)
    return _client


def _get_file_client() -> httpx.Client:
    global _file_client
    if _file_client is None:
        _file_client = httpx.Client(timeout=120.0)
    return _file_client


def _post_with_retry(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    resp = client.post(url, **kwargs)
    if resp.status_code == 429:
        headers = getattr(resp, "headers", None) or {}
        raw = headers.get("Retry-After")
        try:
            delay = float(raw) if raw else _RETRY_AFTER_FALLBACK
        except (TypeError, ValueError):
            delay = _RETRY_AFTER_FALLBACK
        time.sleep(delay)
        resp = client.post(url, **kwargs)
    return resp


def _card_text(job: Job) -> str:
    role = (job.role or job.title or "") or ""
    loc = (job.location or "") or ""
    text = (
        f"<b>{_html.escape(role)}</b>\n"
        f"@ {_html.escape(job.company or '')} | {_html.escape(loc)}{' (Remote)' if job.remote else ''}\n"
        f"Posted: {_html.escape(job.date_posted or '')} ({_html.escape(job.freshness or '')})\n"
        f"Exp: {_html.escape(job.experience_needed or '-')} | Salary: {_html.escape(job.salary_if_present or '-')}\n"
        f"Source: {_html.escape(job.source_name or '')} | Score: {job.confidence_score}\n"
    )
    if getattr(job, "decision", ""):
        text += f"Decision: {_html.escape(job.decision)}\n"
    reasons = getattr(job, "reason", []) or []
    if reasons:
        text += f"Reason: {_html.escape(str(reasons[0]))}\n"
    text += f'<a href="{_html.escape(job.apply_url_direct or "", quote=True)}">Apply directly</a>'
    return text


def _truncate_card(text: str) -> str:
    if len(text) <= _MAX_TEXT_LEN:
        return text
    head = text[: _MAX_TEXT_LEN]
    cut = head.rfind("\n")
    if cut > 0:
        head = head[:cut]
    head = head.rstrip("\n")
    return head[: _MAX_TEXT_LEN - 4] + "\n..."


def send_card(job: Job) -> bool:
    token = _bot_token()
    chat = _chat_id()
    if not token or not chat:
        push_stats["failed"] += 1
        return False
    text = _card_text(job)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if job.apply_url_direct:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "Apply", "url": job.apply_url_direct}]]
        }
    try:
        resp = _post_with_retry(_get_client(), url, json=payload)
        if resp.status_code != 200:
            snippet = (resp.text or "")[:140]
            print(f"[telegram] sendMessage failed: HTTP {resp.status_code} {snippet}")
            push_stats["failed"] += 1
            return False
        push_stats["sent"] += 1
        return True
    except httpx.HTTPError as e:
        print(f"[telegram] sendMessage network error: {e}")
        push_stats["failed"] += 1
        return False


def send_file(path: str, caption: str = "") -> bool:
    token = _bot_token()
    chat = _chat_id()
    if not token or not chat:
        push_stats["failed"] += 1
        return False
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with open(path, "rb") as fh:
            files = {"document": fh}
            data = {"chat_id": chat, "caption": caption[:1024]}
            resp = _post_with_retry(_get_file_client(), url, files=files, data=data)
        if resp.status_code != 200:
            push_stats["failed"] += 1
            return False
        push_stats["sent"] += 1
        return True
    except (httpx.HTTPError, OSError):
        push_stats["failed"] += 1
        return False


def _send_batch(jobs: list[Job]) -> int:
    sent = 0
    for i, job in enumerate(jobs):
        if send_card(job):
            sent += 1
        if i < len(jobs) - 1:
            time.sleep(0.5)
    return sent


def notify_new(jobs: list[Job]) -> int:
    """Push genuinely-new, not-CLOSED jobs that are not hard REJECTs
    (AUTO_ACCEPT + REVIEW). Fuzzy-merged (HIGH) and REJECT jobs never alert."""
    sent = 0
    batch: list[Job] = []
    for j in jobs:
        if not j.genuinely_new or j.authentic_status == "CLOSED":
            continue
        if getattr(j, "decision", "") in ("", "REJECT"):
            continue
        batch.append(j)
        if len(batch) >= _BATCH_SIZE:
            sent += _send_batch(batch)
            batch = []
    if batch:
        sent += _send_batch(batch)
    return sent
