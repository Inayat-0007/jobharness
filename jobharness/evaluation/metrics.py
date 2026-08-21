from __future__ import annotations


def precision_recall_f1(tp: int, fp: int, fn: int) -> dict:
    """Precision / recall / F1 (0.0 when no positives predicted)."""
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def duplicate_metrics(labels: list[int], scores: list[float], threshold: float) -> dict:
    """PRF of duplicate detection at a score threshold (score >= threshold ->
    predicted duplicate)."""
    tp = fp = fn = 0
    for label, score in zip(labels, scores, strict=False):
        pred = score >= threshold
        if pred and label == 1:
            tp += 1
        elif pred and label == 0:
            fp += 1
        elif not pred and label == 1:
            fn += 1
    return precision_recall_f1(tp, fp, fn)


def expected_calibration_error(labels: list[int], scores: list[float], bins: int = 10) -> float:
    """ECE of probability scores vs binary labels (0 = perfectly calibrated)."""
    if not labels:
        return 0.0
    edges = [i / bins for i in range(bins + 1)]
    total = 0.0
    weight_sum = 0
    for lo, hi in zip(edges[:-1], edges[1:], strict=False):
        idx = [i for i, s in enumerate(scores) if lo <= s < hi or (hi == 1.0 and s == 1.0)]
        if not idx:
            continue
        acc = sum(labels[i] for i in idx) / len(idx)
        conf = sum(scores[i] for i in idx) / len(idx)
        total += abs(acc - conf) * len(idx)
        weight_sum += len(idx)
    return round(total / weight_sum, 4) if weight_sum else 0.0
