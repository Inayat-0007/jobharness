from __future__ import annotations

import urllib.parse

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
    text = (
        f"*{role}*\n"
        f"@ {job.company} | {job.location}{' (Remote)' if job.remote else ''}\n"
        f"Posted: {job.date_posted or '-'} ({job.freshness})\n"
        f"Exp: {job.experience_needed or '-'} | Salary: {job.salary_if_present or '-'}\n"
        f"Source: {job.source_name}\n"
        f"[Apply directly]({job.apply_url_direct})"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                json={
                    "chat_id": chat,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                },
            )
            return resp.status_code == 200
    except httpx.HTTPError:
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
    sent = 0
    for j in jobs:
        if not j.genuinely_new or j.authentic_status == "CLOSED":
            continue
        if send_card(j):
            sent += 1
    return sent


def safe_url(url: str) -> str:
    return urllib.parse.quote(url, safe=":/?&=%")
