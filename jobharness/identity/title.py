from __future__ import annotations

from ..algo import normalize_text
from ..algo import title_stem as _algo_title_stem


def normalize_title(title) -> str:
    """Lowercased, whitespace-collapsed, punctuation-stripped title. Single
    implementation in algo.py (normalize_text)."""
    return normalize_text(title)


def title_stem(title) -> str:
    """First 2 normalized title tokens (seniority words removed). Single
    implementation in algo.py."""
    return _algo_title_stem(title)
