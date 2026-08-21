from __future__ import annotations


class SourceFetchError(Exception):
    """Base class for typed per-source fetch failures.

    Browser (Playwright) adapters raise one of the subclasses below instead of
    swallowing the failure into an empty list, so the runner can record a real
    SourceStatus (runner.py maps each class to a status; unknown exceptions
    fall back to SOURCE_DOWN).
    """


class RateLimitedError(SourceFetchError):
    """Source explicitly rate-limited us (HTTP 429 / 'too many requests').

    Raised by browser adapters only when the site itself reports rate
    limiting. Generic block walls (CAPTCHA, 'access denied', 'unusual
    traffic') are BlockedError, not this class.
    """


class AuthRequiredError(SourceFetchError):
    """Source needs a key/credential we do not have (401, login wall).

    Browser adapters raise this when the site redirects to a login wall and
    the manual `wait_for_login` gate times out, on both the desktop and the
    mobile-context retry. Runner maps it to AUTH_REQUIRED.
    """


class SourceDownError(SourceFetchError):
    """Source unreachable / 5xx / transport failure.

    Browser adapters raise this when page navigation fails (goto timeout,
    connection refused) after the mobile-context fallback retry, or when a
    browser/context launch fails for the whole adapter. Runner maps it to
    SOURCE_DOWN.
    """


class ParseFailureError(SourceFetchError):
    """Source responded but the payload could not be parsed.

    Browser adapters raise this when the site rendered (no transport or block
    error) but the expected DOM shape produced no job data at all across
    every page. Runner maps it to PARSE_FAILURE.
    """


class BlockedError(SourceFetchError):
    """Source responded with a block page (CAPTCHA wall, 'access denied').

    Browser adapters raise this when `detect_block` reports 'captcha' or
    'denied' and the manual CAPTCHA gate times out, or when a failed
    navigation lands on a block page. Runner maps it to BLOCKED.
    """
