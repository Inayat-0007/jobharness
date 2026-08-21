from __future__ import annotations

import os
import random
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Optional

from . import secrets
from .fetcher import pick_proxy, UA_POOL


_BROWSER_LOCK = threading.Lock()

# Optional: point at the user's REAL Chrome profile (e.g. the `User Data` dir).
# The gated sources then open with the user's existing LinkedIn/Naukri/Hirist
# logins - no login walls, no Google reCAPTCHA. Chrome must be fully closed
# while the harness runs (the profile is locked by the first Chrome instance).
_REAL_PROFILE = os.environ.get("BROWSER_USER_DATA_DIR", "").strip() or None


def _context_dir(source: str) -> str:
    if _REAL_PROFILE:
        return _REAL_PROFILE
    return str(cookie_path(source))


def cookie_dir() -> Path:
    p = Path(__file__).resolve().parent.parent / "cookies"
    p.mkdir(exist_ok=True)
    (p / ".gitkeep").touch(exist_ok=True)
    # Mark the cookies dir private if possible (POSIX); no-op on Windows.
    try:
        Path.chmod(p, 0o700)
    except (PermissionError, OSError):
        pass
    return p


def cookie_path(source: str) -> Path:
    return cookie_dir() / f"{source}.json"


RECAPTCHA_ERROR_MARKERS = (
    "could not connect to the recaptcha service",
    "unable to load recaptcha",
    "recaptcha failed to load",
    "error loading recaptcha",
)


def recaptcha_error(page) -> bool:
    """True when the page shows Google's 'could not connect to the reCAPTCHA
    service' error - the challenge iframe failed to load."""
    try:
        html = (page.content() or "").lower()
    except Exception:
        return False
    return any(m in html for m in RECAPTCHA_ERROR_MARKERS)


def _reload_for_recaptcha(page, source: str, reloads: list) -> None:
    """If the page shows the reCAPTCHA-load failure, reload it (the site's own
    suggested fix) up to `max_reloads` times, waiting for the challenge to load.

    If the error persists, it is usually Google's anti-bot flagging the session
    (especially in the Google sign-in popup) - the user should log in with
    email + password instead of Google OAuth.
    """
    if not reloads or reloads[0] <= 0:
        return
    try:
        if recaptcha_error(page):
            print(
                f"[{source}] reCAPTCHA failed to load - reloading page (attempts left: {reloads[0]}). "
                f"If this is a Google sign-in popup and the error keeps returning, close the popup "
                f"and log in with email + password instead of Google."
            )
            page.reload(timeout=60000, wait_until="domcontentloaded")
            reloads[0] -= 1
            time.sleep(4)
    except Exception:
        pass


def wait_for_login(page, source: str, url: str, is_login_wall, timeout: int = 600) -> bool:
    """Poll the open browser until the human finishes logging in.

    Every few seconds checks whether the login wall is gone; when it is,
    re-navigates to ``url`` and returns True. If the login page shows the
    'could not connect to the reCAPTCHA service' error, the page is reloaded
    (up to 3 times) to re-trigger a working challenge. Returns False after
    timeout. No console interaction needed - the run continues automatically.
    """
    print(f"[{source}] browser open - please log in there. The run will continue automatically once done.")
    reloads = [3]
    waited = 0
    while waited < timeout:
        time.sleep(3)
        waited += 3
        _reload_for_recaptcha(page, source, reloads)
        try:
            if not is_login_wall(page):
                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                except Exception:
                    pass
                time.sleep(2)
                return not is_login_wall(page)
        except Exception:
            pass
        if waited % 30 == 0:
            print(f"[{source}] still waiting for login... ({waited}s)")
    print(f"[{source}] login wait timed out after {timeout}s")
    return False


def wait_for_captcha(page, source: str, timeout: int = 600) -> bool:
    """Poll until the human solves the CAPTCHA (block markers disappear).

    If the page shows Google's reCAPTCHA-load failure, it is reloaded (up to 3
    times) to re-trigger the challenge. Returns True when solved, False on
    timeout. No console interaction.
    """
    print(f"[{source}] CAPTCHA - please solve it in the browser window. The run will continue automatically once done.")
    reloads = [3]
    waited = 0
    while waited < timeout:
        time.sleep(3)
        waited += 3
        _reload_for_recaptcha(page, source, reloads)
        try:
            if detect_block(page) != "captcha":
                return True
        except Exception as e:
            print(f"[{source}] CAPTCHA check error: {e}")
            return False
        if waited % 30 == 0:
            print(f"[{source}] still waiting for CAPTCHA... ({waited}s)")
    print(f"[{source}] CAPTCHA wait timed out after {timeout}s")
    return False


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


def launch_stealth_context(
    p,
    *,
    source: str,
    headless: bool,
    mobile: bool = False,
    timezone_id: str = "America/New_York",
    locale: str = "en-US",
    use_real_profile: bool = True,
):
    """Launch a persistent, stealth-hardened Chromium context for gated scrapers.

    Prefers the user's real Chrome (channel="chrome") over the bundled Chromium:
    the bundled build ships automation flags that portals (Naukri/Hirist/
    LinkedIn) use to refuse logins. Falls back to bundled Chromium if Chrome is
    not launchable. HTTPS errors are ignored so certificate warning pages
    ("your connection is not secure") never block a run.

    When BROWSER_USER_DATA_DIR is set, launches with the user's real Chrome
    profile (their existing portal logins) instead of a fresh per-source
    profile. The browser then presents a fully trusted session - no login
    walls, no Google reCAPTCHA. If the profile is locked (Chrome open), falls
    back to the per-source profile with a clear message.
    """
    cpath = _context_dir(source) if use_real_profile else str(cookie_path(source))
    proxy = pick_proxy()
    proxy_opts = {"server": proxy} if proxy else None

    viewport = (390, 844) if mobile else (1366, 900)
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        if mobile
        else random.choice(UA_POOL)
    )

    launch_opts = dict(
        headless=headless,
        proxy=proxy_opts,
        viewport={"width": viewport[0], "height": viewport[1]},
        is_mobile=mobile,
        has_touch=mobile,
        device_scale_factor=2 if mobile else 1,
        ignore_https_errors=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            "--disable-component-update",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--window-size=1366,900",
        ],
    )
    # A real profile already carries the user's own UA/locale/timezone; faking
    # them would fingerprint-mismatch the existing cookies. Fresh profiles get
    # the stealth fingerprint (India portals get Asia/Kolkata + en-IN).
    if _REAL_PROFILE:
        pass
    else:
        launch_opts["user_agent"] = ua
        launch_opts["locale"] = locale
        launch_opts["timezone_id"] = timezone_id
    try:
        context = p.chromium.launch_persistent_context(cpath, channel="chrome", **launch_opts)
    except Exception as e:
        if _REAL_PROFILE:
            print(
                f"[browser] could not open real Chrome profile ({e}). "
                f"Close Chrome completely and rerun, or unset BROWSER_USER_DATA_DIR. "
                f"Falling back to per-source profile."
            )
            cpath = str(cookie_path(source))
            launch_opts["user_agent"] = ua
            launch_opts["locale"] = locale
            launch_opts["timezone_id"] = timezone_id
            context = p.chromium.launch_persistent_context(cpath, **launch_opts)
        else:
            print(f"[browser] real Chrome unavailable ({e}); falling back to bundled Chromium")
            context = p.chromium.launch_persistent_context(cpath, **launch_opts)
    apply_stealth(context)
    return context


STEALTH_JS = r"""
(() => {
  const patch = () => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'userAgentData', { get: () => undefined });
    window.chrome = window.chrome || {};
    window.chrome.runtime = window.chrome.runtime || {};
    window.chrome.loadTimes = window.chrome.loadTimes || (() => ({}));
    window.chrome.csi = window.chrome.csi || (() => ({}));
    const q = window.navigator.permissions && window.navigator.permissions.query;
    if (q) {
      window.navigator.permissions.query = (p) => (
        p && p.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : q(p)
      );
    }
    if (window.outerWidth === 0 && window.outerHeight === 0) {
      Object.defineProperty(window, 'outerWidth', { get: () => 1366 });
      Object.defineProperty(window, 'outerHeight', { get: () => 900 });
    }
  };
  patch();
  document.addEventListener('DOMContentLoaded', patch, { once: true });
})();
"""


def apply_stealth(context) -> None:
    """Stealth on EVERY page of the context (init scripts apply to popups too).

    Context-level init script covers all current + future pages (login popups,
    redirects); playwright-stealth additionally patches the first page when
    installed. No automated CAPTCHA solving anywhere.
    """
    try:
        context.add_init_script(STEALTH_JS)
    except Exception:
        pass
    try:
        from playwright_stealth import stealth_sync  # type: ignore
    except ImportError:
        stealth_sync = None
    page = context.pages[0] if context.pages else context.new_page()
    if stealth_sync is not None:
        try:
            stealth_sync(page)
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
def open_browser(
    source: str,
    headless: bool,
    mobile: bool = False,
    *,
    timezone_id: str = "America/New_York",
    locale: str = "en-US",
    use_real_profile: bool = True,
    serialize: bool = True,
):
    """Context manager that yields (playwright, context) and always closes cleanly.

    Serialized by default: only one browser context runs at a time (a global
    lock), so login/CAPTCHA prompts are never stacked on the same console, and
    portal sessions do not overlap. `serialize=False` lets adapters that need
    no human interaction (e.g. headless career-page rendering) run several
    contexts in parallel. `timezone_id`/`locale` let per-portal adapters
    present a natural fingerprint (e.g. Asia/Kolkata + en-IN for Indian sites).
    """
    from playwright.sync_api import sync_playwright

    lock = _BROWSER_LOCK if serialize else nullcontext()
    with lock:
        p = sync_playwright().start()
        context = None
        try:
            context = launch_stealth_context(
                p,
                source=source,
                headless=headless,
                mobile=mobile,
                timezone_id=timezone_id,
                locale=locale,
                use_real_profile=use_real_profile,
            )
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
