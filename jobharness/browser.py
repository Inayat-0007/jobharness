from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import secrets


def cookie_dir() -> Path:
    p = Path(__file__).resolve().parent.parent / "cookies"
    p.mkdir(exist_ok=True)
    return p


def cookie_path(source: str) -> Path:
    return cookie_dir() / f"{source}.json"


def pick_proxy() -> Optional[str]:
    return secrets.proxy_list() and secrets.proxy_list()[0] or None


CAPTCHA_NOTICE = """\n========================================
[CAPTCHA REQUIRED] A CAPTCHA appeared on {source}.
A browser window is open. Please solve it there, THEN come back here
and press ENTER to continue the run.
========================================\n"""


def manual_captcha_wait(source: str, cap: bool) -> None:
    if not cap:
        return
    print(CAPTCHA_NOTICE.format(source=source))
    try:
        input("Press ENTER after solving the CAPTCHA...")
    except EOFError:
        pass
