from __future__ import annotations

import random
import time
from typing import Optional

import httpx

from . import secrets


UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def pick_proxy() -> Optional[str]:
    proxies = secrets.proxy_list()
    if not proxies:
        return None
    return random.choice(proxies)


def random_delay(low: float = 0.5, high: float = 2.0) -> None:
    time.sleep(random.uniform(low, high))


def make_client(timeout: float = 30.0) -> httpx.Client:
    proxy = pick_proxy()
    client_kwargs = dict(
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": random.choice(UA_POOL),
            "Accept": "text/html,application/json,application/xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    if proxy:
        client_kwargs["proxy"] = proxy
    return httpx.Client(**client_kwargs)


def resp_text(resp: httpx.Response) -> str:
    """Decode a response body without raising UnicodeDecodeError.

    Some portals serve mislabeled encodings; use the bytes with replacement
    characters so parsing degrades gracefully instead of crashing.
    """
    try:
        return resp.text or ""
    except UnicodeDecodeError:
        return (resp.content or b"").decode("utf-8", errors="replace")


def blocked_response(resp: httpx.Response) -> bool:
    status = resp.status_code
    if status in (403, 429):
        return True
    body_snippet = resp_text(resp)[:2000].lower()
    markers = ("captcha", "are you a robot", "access denied", "unusual traffic", "verify you are human")
    return any(m in body_snippet for m in markers)


def classify_response(resp: httpx.Response):
    """Map an httpx.Response to a typed SourceStatus (None when healthy).

    Adapters may use this to raise the typed exceptions in
    `jobharness.sources.exceptions`; the runner also maps fetch outcomes.
    """
    from .evidence.source import SourceStatus

    if resp.status_code == 429 or "rate limit" in resp_text(resp).lower():
        return SourceStatus.RATE_LIMITED
    if resp.status_code == 401:
        return SourceStatus.AUTH_REQUIRED
    if resp.status_code >= 500:
        return SourceStatus.SOURCE_DOWN
    if blocked_response(resp):
        return SourceStatus.BLOCKED
    return None
