from __future__ import annotations

from urllib.parse import urlsplit

TRACKING_PARAMS = {"fbclid", "campaign", "source", "tracking"}


def canonicalize_url(url) -> str:
    """Canonical form: lowercase scheme/host, www stripped, default port and
    trailing slash removed, tracking params (utm_*, fbclid, campaign, source,
    tracking) dropped. Order of remaining query params is preserved.
    """
    if not url:
        return ""
    s = str(url).strip()
    try:
        parts = urlsplit(s)
    except ValueError:
        return s
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if ":" in host:
        hostname, _, port = host.rpartition(":")
        if port in ("80", "443"):
            host = hostname
    path = parts.path.rstrip("/")
    keep = []
    for kv in parts.query.split("&"):
        if not kv:
            continue
        key = kv.split("=", 1)[0].lower()
        if key.startswith("utm_") or key in TRACKING_PARAMS:
            continue
        keep.append(kv)
    out = f"{scheme}://{host}{path}"
    if keep:
        out += "?" + "&".join(keep)
    return out


def apply_url_domain(url) -> str:
    """Extract the registrable-looking host from a URL (no scheme, no www,
    no userinfo). Canonical home of the domain-extraction logic; verify.py
    delegates here."""
    if not url:
        return ""
    try:
        net = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    net = net.split("@")[-1]
    if net.startswith("www."):
        net = net[4:]
    return net
