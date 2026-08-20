from __future__ import annotations


class SourceFetchError(Exception):
    """Base class for typed per-source fetch failures."""


class RateLimitedError(SourceFetchError):
    """Source responded 429 or otherwise rate-limited us."""


class AuthRequiredError(SourceFetchError):
    """Source needs a key/credential we do not have (401)."""


class SourceDownError(SourceFetchError):
    """Source unreachable / 5xx / transport failure."""


class ParseFailureError(SourceFetchError):
    """Source responded but the payload could not be parsed."""
