from __future__ import annotations

from .dataset import generate_dataset, write_dataset, load_dataset
from .metrics import precision_recall_f1, duplicate_metrics, expected_calibration_error
from .calibration import platt_scale, calibrate
from .fellegi_sunter import m_u_estimates, pair_weight, classify

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
