"""Offline benchmark: `python -m jobharness.evaluation.benchmark`.

Metrics table for dedup (composite similarity), authenticity, and matching
(scoring). Runs entirely on the deterministic synthetic dataset — no network,
no production wiring. Statistical thresholds only reach production after
real labeled data exists (GATE: Phase 4).
"""

from __future__ import annotations

from .. import algo
from ..evidence.source import source_authority
from ..models import Job
from ..scoring.authenticity import authenticity_score
from ..scoring.matching import score_match
from .calibration import calibrate, platt_scale
from .dataset import generate_dataset
from .fellegi_sunter import m_u_estimates, pair_weight
from .metrics import duplicate_metrics, expected_calibration_error


def _pair_similarity(pair: dict) -> float:
    a, b = pair["a"], pair["b"]
    _, s = algo.composite_similarity(
        a.get("title", ""), a.get("company", ""), a.get("location", ""), a.get("description", ""),
        b.get("title", ""), b.get("company", ""), b.get("location", ""), b.get("description", ""),
        url1=a.get("apply_url_direct", ""), url2=b.get("apply_url_direct", ""),
    )
    return s


def benchmark_dedup(pairs: list[dict]) -> None:
    print("\n== dedup (composite similarity) ==")
    labels = [p["label"] for p in pairs]
    scores = [_pair_similarity(p) for p in pairs]
    for t in (0.75, 0.80, 0.88):
        m = duplicate_metrics(labels, scores, t)
        print(f"  threshold {t:.2f}: precision={m['precision']} recall={m['recall']} f1={m['f1']}")
    print(f"  identity-score ECE: {expected_calibration_error(labels, scores)}")
    a, b = platt_scale(labels, scores)
    cal = calibrate(scores, a, b)
    print(f"  post-Platt ECE: {expected_calibration_error(labels, cal)}")
    est = m_u_estimates(pairs)
    weights = [pair_weight(p, est) for p in pairs]
    for t in (1.0, 2.0):
        m = duplicate_metrics(labels, weights, t)
        print(f"  Fellegi-Sunter weight>={t}: precision={m['precision']} recall={m['recall']} f1={m['f1']}")


def _authentic_job(closed: bool) -> Job:
    j = Job(
        title="Backend Engineer", company="Acme", location="Remote",
        description="python api backend", experience_needed="5+ years",
    )
    j.source_name = "greenhouse"
    j.source_authority = source_authority("greenhouse")
    j.apply_url_direct = "https://careers.acme.com/jobs/4123456"
    j.employer_domain = "careers.acme.com"
    j.posting_id = "4123456"
    j.date_posted = "2023-11-14"
    j.freshness = "fresh"
    j.valid_through = "2000-01-01" if closed else "2099-12-31"
    j.authentic_status = "CLOSED" if closed else "AUTHENTIC"
    return j


def benchmark_authenticity() -> None:
    print("\n== authenticity (raw heuristic, not probability) ==")
    jobs = [_authentic_job(True) for _ in range(40)] + [_authentic_job(False) for _ in range(40)]
    labels = [1 if j.authentic_status == "AUTHENTIC" else 0 for j in jobs]
    scores = [authenticity_score(j) for j in jobs]
    for t in (40, 50, 70):
        m = duplicate_metrics(labels, scores, t)
        print(f"  threshold {t}: precision={m['precision']} recall={m['recall']} f1={m['f1']}")


def benchmark_matching() -> None:
    print("\n== matching (score_match vs profile) ==")
    from ..profile import Profile

    profile = Profile(roles=["Backend Engineer"], keywords=["python"], remote=True)
    relevant = [
        Job(title="Backend Engineer", description="python api services backend engineer", remote=True, location="Remote")
        for _ in range(40)
    ]
    irrelevant = [
        Job(title="Marketing Lead", description="brand campaigns growth funnels", remote=True, location="Remote")
        for _ in range(40)
    ]
    labels = [1] * 40 + [0] * 40
    scores = [score_match(j, profile) for j in relevant + irrelevant]
    for t in (0.4, 0.6):
        m = duplicate_metrics(labels, scores, t)
        print(f"  threshold {t}: precision={m['precision']} recall={m['recall']} f1={m['f1']}")


def main() -> None:
    pairs = generate_dataset(seed=42, n_pairs=200)
    labels = [p["label"] for p in pairs]
    print(f"labeled pairs: {len(pairs)} (positives={sum(labels)}, negatives={len(labels) - sum(labels)})")
    benchmark_dedup(pairs)
    benchmark_authenticity()
    benchmark_matching()


if __name__ == "__main__":
    main()
