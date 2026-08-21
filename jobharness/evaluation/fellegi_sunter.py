"""Fellegi-Sunter linkage weights (experiment module only).

m_i = P(agree on field i | same entity), u_i = P(agree on field i | distinct).
Agreement weight W_i = log2(m_i/u_i); disagreement weight log2((1-m_i)/(1-u_i)).
Totals classify pairs into HIGH / MIDDLE / LOW linkage. NOT wired into the
production path until benchmark results justify it.
"""

from __future__ import annotations

import math

FIELDS = ("title", "company", "location", "description")


def m_u_estimates(pairs: list[dict], fields: tuple = FIELDS) -> dict:
    """Estimate m/u per field from labeled pairs.

    `pairs`: list of {"a": {...}, "b": {...}, "label": 0|1}. Field agreement
    is exact equality of normalized text (plan: deterministic before
    probabilistic — the production path keeps composite similarity).
    """
    from ..algo import normalize_text

    estimates = {}
    for f in fields:
        agree_dup = agree_dist = dup_total = dist_total = 0
        for p in pairs:
            a = normalize_text(p["a"].get(f, ""))
            b = normalize_text(p["b"].get(f, ""))
            agree = bool(a) and bool(b) and a == b
            if p["label"] == 1:
                dup_total += 1
                agree_dup += int(agree)
            else:
                dist_total += 1
                agree_dist += int(agree)
        m = (agree_dup + 1) / (dup_total + 2) if dup_total else 0.5
        u = (agree_dist + 1) / (dist_total + 2) if dist_total else 0.5
        estimates[f] = {"m": m, "u": u}
    return estimates


def pair_weight(pair: dict, estimates: dict, fields: tuple = FIELDS) -> float:
    """Log2 Fellegi-Sunter total weight for one pair."""
    from ..algo import normalize_text

    total = 0.0
    for f in fields:
        a = normalize_text(pair["a"].get(f, ""))
        b = normalize_text(pair["b"].get(f, ""))
        agree = bool(a) and bool(b) and a == b
        e = estimates[f]
        total += math.log2(e["m"] / e["u"]) if agree else math.log2((1 - e["m"]) / (1 - e["u"]))
    return round(total, 4)


def classify(weight: float, low: float, high: float) -> str:
    if weight >= high:
        return "HIGH"
    if weight >= low:
        return "MIDDLE"
    return "LOW"
