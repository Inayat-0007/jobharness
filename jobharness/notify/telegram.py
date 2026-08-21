from __future__ import annotations

import html as _html

import httpx

from .. import secrets
from ..models import Job


def _bot_token() -> str:
    return secrets.get("TELEGRAM_BOT_TOKEN", "")


def _chat_id() -> str:
    return secrets.get("TELEGRAM_CHAT_ID", "")


def configured() -> bool:
    return bool(_bot_token() and _chat_id())


def send_card(job: Job) -> bool:
    token = _bot_token()
    chat = _chat_id()
    if not token or not chat:
        return False
    role = job.role or job.title
    loc = job.location or ""
    text = (
        f"<b>{_html.escape(role)}</b>\n"
        f"@ {_html.escape(job.company)} | {_html.escape(loc)}{' (Remote)' if job.remote else ''}\n"
        f"Posted: {_html.escape(job.date_posted)} ({_html.escape(job.freshness or '')})\n"
        f"Exp: {_html.escape(job.experience_needed or '-')} | Salary: {_html.escape(job.salary_if_present or '-')}\n"
        f"Source: {_html.escape(job.source_name or '')} | Score: {job.confidence_score}\n"
    )
    if getattr(job, "decision", ""):
        text += f"Decision: {_html.escape(job.decision)}\n"
    reasons = getattr(job, "reason", []) or []
    if reasons:
        text += f"Reason: {_html.escape(str(reasons[0]))}\n"
    text += f'<a href="{_html.escape(job.apply_url_direct, quote=True)}">Apply directly</a>'
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                json={
                    "chat_id": chat,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
            )
            if resp.status_code != 200:
                snippet = (resp.text or "")[:140]
                print(f"[telegram] sendMessage failed: HTTP {resp.status_code} {snippet}")
            return resp.status_code == 200
    except httpx.HTTPError as e:
        print(f"[telegram] sendMessage network error: {e}")
        return False



def send_file(path: str, caption: str = "") -> bool:
    token = _bot_token()
    chat = _chat_id()
    if not token or not chat:
        return False
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with httpx.Client(timeout=120.0) as client:
            with open(path, "rb") as fh:
                files = {"document": fh}
                data = {"chat_id": chat, "caption": caption[:1024]}
                resp = client.post(url, files=files, data=data)
            return resp.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def notify_new(jobs: list[Job]) -> int:
    """Push genuinely-new, not-CLOSED jobs that are not hard REJECTs
    (AUTO_ACCEPT + REVIEW). Fuzzy-merged (HIGH) and REJECT jobs never alert."""
    sent = 0
    for j in jobs:
        if not j.genuinely_new or j.authentic_status == "CLOSED":
            continue
        if getattr(j, "decision", "") in ("", "REJECT"):
            continue
        if send_card(j):
            sent += 1
    return sent
