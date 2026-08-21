"""Probability calibration (Platt scaling) with pure-Python gradient descent.

Phase 4 experiment module. NOT wired into the production path until the
labeled dataset exists and benchmark results justify it. scikit-learn is only
an optional `ml` extra; this module works without it.
"""

from __future__ import annotations

import math


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def platt_scale(labels: list[int], scores: list[float], iters: int = 300, lr: float = 0.5) -> tuple[float, float]:
    """Fit P(y=1|x) = sigmoid(a*x + b) by log-loss gradient descent.

    Returns (a, b). Scores are clipped to [0,1] to avoid extremes.
    """
    xs = [min(1.0, max(0.0, s)) for s in scores]
    a, b = 1.0, 0.0
    n = max(1, len(xs))
    for _ in range(iters):
        ga = gb = 0.0
        for x, y in zip(xs, labels, strict=False):
            p = _sigmoid(a * x + b)
            ga += (p - y) * x
            gb += p - y
        a -= lr * ga / n
        b -= lr * gb / n
    return a, b


def calibrate(scores: list[float], a: float, b: float) -> list[float]:
    return [_sigmoid(a * s + b) for s in scores]
