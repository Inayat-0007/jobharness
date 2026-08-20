from __future__ import annotations

from .. import algo


def authenticity_score(job, verify_result=None) -> float:
    """Weighted raw authenticity heuristic (0-100), feature-driven.

    Never called "probability" — it is a stored raw heuristic until Phase 4
    calibration produces data-backed probabilities.
    """
    feats = algo.authenticity_features(job)
    score = 0.0
    score += feats["source_authority"] * 5.0      # max 25
    score += feats["domain_match"] * 15.0         # max 15
    score += feats["posting_id"] * 5.0            # max 5
    score += feats["http_status"] * 15.0          # max 15
    score += feats["validThrough"] * 5.0          # max 5
    score += feats["freshness"] * 10.0            # max 10
    score += feats["completeness"] * 10.0         # max 10
    score += feats["cross_source"] * 10.0         # max 10
    score -= feats["closed_markers"] * 15.0
    return round(max(0.0, min(100.0, score)), 2)
