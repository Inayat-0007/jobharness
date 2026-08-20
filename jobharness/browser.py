from __future__ import annotations

import random
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from . import secrets
from .fetcher import pick_proxy, UA_POOL


def cookie_dir() -> Path:
    p = Path(__file__).resolve().parent.parent / "cookies"
    p.mkdir(exist_ok=True)
    (p / ".gitkeep").touch(exist_ok=True)
    # Mark the cookies dir private if possible (POSIX); no-op on Windows.
    try:
        Path.chmod(cookie_dir(), 0o700)
    except (PermissionError, OSError):
        pass
    return p


def cookie_path(source: str) -> Path:
    return cookie_dir() / f"{source}.json"


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


CAPTCHA_MARKERS = (
    "captcha",
    "verify you are human",
    "verify you're human",
    "are you a robot",
    "security verification",
    "unusual traffic",
    "trust and safety",
    "access denied",
    "blocked",
)


def detect_block(page) -> str:
    """Return a block reason string ('captcha' / 'denied' / '') or '' if clean."""
    try:
        html = (page.content() or "").lower()
    except Exception:
        return ""
    for m in ("captcha", "verify you are human", "are you a robot", "security verification"):
        if m in html:
            return "captcha"
    for m in ("unusual traffic", "access denied", "trust and safety", "blocked", "you have been blocked"):
        if m in html:
            return "denied"
    return ""


def launch_stealth_context(p, *, source: str, headless: bool, mobile: bool = False):
    """Launch a persistent, stealth-hardened Chromium context for gated scrapers."""
    cpath = str(cookie_path(source))
    proxy = pick_proxy()
    proxy_opts = {"server": proxy} if proxy else None

    viewport = (390, 844) if mobile else (1366, 900)
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        if mobile
        else random.choice(UA_POOL)
    )

    context = p.chromium.launch_persistent_context(
        cpath,
        headless=headless,
        proxy=proxy_opts,
        viewport={"width": viewport[0], "height": viewport[1]},
        user_agent=ua,
        locale="en-US",
        timezone_id="America/New_York",
        is_mobile=mobile,
        has_touch=mobile,
        device_scale_factor=2 if mobile else 1,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
        ],
    )
    apply_stealth(context)
    return context


def apply_stealth(context) -> None:
    """Best-effort playwright-stealth; fall back to manual navigator.webdriver patch."""
    try:
        from playwright_stealth import stealth_sync  # type: ignore
    except ImportError:
        stealth_sync = None
    page = context.pages[0] if context.pages else context.new_page()
    if stealth_sync is not None:
        try:
            stealth_sync(page)
            return
        except Exception:
            pass
    try:
        page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
            "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
            "window.chrome={runtime:{}};"
        )
    except Exception:
        pass


def scroll_to_load(page, *, max_scrolls: int = 6, pause: float = 0.8) -> None:
    """Scroll down to trigger lazy-loaded job cards; stop when page stops growing."""
    last_height = 0
    for _ in range(max_scrolls):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            break
        time.sleep(pause)
        try:
            h = page.evaluate("document.body.scrollHeight")
        except Exception:
            break
        if h == last_height:
            break
        last_height = h
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


@contextmanager
def open_browser(source: str, headless: bool, mobile: bool = False):
    """Context manager that yields (playwright, context) and always closes cleanly."""
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    context = None
    try:
        context = launch_stealth_context(p, source=source, headless=headless, mobile=mobile)
        yield p, context
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass


def wait_for_selector_any(page, selectors: list[str], timeout: int = 20000):
    """Wait for the first of several selectors, return the matched one or ''."""
    combined = ", ".join(selectors)
    try:
        page.wait_for_selector(combined, timeout=timeout)
        for s in selectors:
            if page.query_selector(s):
                return s
        return selectors[0]
    except Exception:
        return ""
