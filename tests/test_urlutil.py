from __future__ import annotations

from jobharness.urlutil import canonicalize_url, apply_url_domain


def test_utm_params_stripped():
    u = "https://acme.com/j/1?utm_source=newsletter&utm_medium=email&id=42&utm_campaign=q3"
    assert canonicalize_url(u) == "https://acme.com/j/1?id=42"


def test_tracking_params_stripped():
    u = "https://acme.com/j/1?fbclid=abc&campaign=x&source=y&tracking=z&real=1"
    assert canonicalize_url(u) == "https://acme.com/j/1?real=1"


def test_param_order_preserved():
    u = "https://acme.com/j/1?b=2&a=1&utm_x=9"
    assert canonicalize_url(u) == "https://acme.com/j/1?b=2&a=1"


def test_trailing_slash_removed():
    assert canonicalize_url("https://acme.com/j/1/") == "https://acme.com/j/1"


def test_idempotent_stability():
    u = "https://acme.com/j/1?utm_source=x&a=1"
    once = canonicalize_url(u)
    assert canonicalize_url(once) == once


def test_host_normalization():
    assert canonicalize_url("HTTPS://WWW.Acme.com:443/j/1") == "https://acme.com/j/1"


def test_nondefault_port_kept():
    assert canonicalize_url("https://acme.com:8080/j") == "https://acme.com:8080/j"


def test_empty_and_invalid_urls():
    assert canonicalize_url("") == ""
    assert canonicalize_url(None) == ""


def test_apply_url_domain():
    assert apply_url_domain("https://www.Acme.com/careers/1") == "acme.com"
    assert apply_url_domain("http://boards.greenhouse.io/acme") == "boards.greenhouse.io"
    assert apply_url_domain("https://user:pw@jobs.example.com/x") == "jobs.example.com"
    assert apply_url_domain("") == ""
