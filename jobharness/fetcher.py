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
    transport_kwargs = {}
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


def blocked_response(resp: httpx.Response) -> bool:
    status = resp.status_code
    if status in (403, 429):
        return True
    body_snippet = (resp.text or "")[:2000].lower()
    markers = ("captcha", "are you a robot", "access denied", "unusual traffic", "verify you are human")
    return any(m in body_snippet for m in markers)
