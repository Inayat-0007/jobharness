from __future__ import annotations

from jobharness.evaluation.dataset import generate_dataset, load_dataset
from jobharness.evaluation.metrics import precision_recall_f1, duplicate_metrics, expected_calibration_error
from jobharness.evaluation.calibration import platt_scale, calibrate
from jobharness.evaluation.fellegi_sunter import m_u_estimates, pair_weight


def test_dataset_generation_counts():
    pairs = generate_dataset(seed=42, n_pairs=200)
    assert len(pairs) == 200
    labels = [p["label"] for p in pairs]
    assert sum(labels) > 50  # at least some positives
    assert sum(labels) < 150  # at least some negatives


def test_dataset_round_trip(tmp_path):
    pairs = generate_dataset(seed=1, n_pairs=20)
    from jobharness.evaluation.dataset import write_dataset
    p = tmp_path / "dataset.jsonl"
    write_dataset(pairs, p)
    loaded = load_dataset(p)
    assert len(loaded) == 20
    for i, lp in enumerate(loaded):
        assert lp["label"] == pairs[i]["label"]


def test_metrics():
    m = precision_recall_f1(10, 2, 3)
    assert 0 < m["precision"] < 1
    assert 0 < m["recall"] < 1
    assert 0 < m["f1"] < 1

    zero = precision_recall_f1(0, 0, 0)
    assert zero == {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    labels = [1, 1, 0, 0]
    scores = [0.9, 0.6, 0.3, 0.1]
    dm = duplicate_metrics(labels, scores, 0.5)
    assert dm["precision"] == 1.0
    assert dm["recall"] == 1.0
    assert dm["f1"] == 1.0

    ece = expected_calibration_error(labels, scores)
    assert 0.0 <= ece <= 1.0


def test_calibration():
    xs = [0.1, 0.3, 0.5, 0.7, 0.9]
    ys = [0, 0, 1, 1, 1]
    a, b = platt_scale(ys, xs, iters=50)
    cal = calibrate(xs, a, b)
    assert len(cal) == len(xs)
    assert all(0.0 <= v <= 1.0 for v in cal)


def test_fellegi_sunter():
    pairs = [
        {"a": {"title": "Backend Engineer", "company": "Acme", "location": "Remote", "description": "python api"},
         "b": {"title": "Backend Engineer", "company": "Acme", "location": "Remote", "description": "python api"},
         "label": 1},
        {"a": {"title": "Backend Engineer", "company": "Acme", "location": "Remote", "description": "python api"},
         "b": {"title": "Frontend Engineer", "company": "Globex", "location": "New York", "description": "react"},
         "label": 0},
    ]
    est = m_u_estimates(pairs)
    for f in ("title", "company", "location", "description"):
        assert f in est
        assert 0 < est[f]["m"] < 1
        assert 0 < est[f]["u"] < 1
    w = pair_weight(pairs[0], est)
    assert w > 0  # agreeing pair -> positive weight