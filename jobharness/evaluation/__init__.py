from __future__ import annotations

from .calibration import calibrate, platt_scale
from .dataset import generate_dataset, load_dataset, write_dataset
from .fellegi_sunter import classify, m_u_estimates, pair_weight
from .metrics import duplicate_metrics, expected_calibration_error, precision_recall_f1

__all__ = [
    "generate_dataset",
    "write_dataset",
    "load_dataset",
    "precision_recall_f1",
    "duplicate_metrics",
    "expected_calibration_error",
    "platt_scale",
    "calibrate",
    "m_u_estimates",
    "pair_weight",
    "classify",
]
