from __future__ import annotations

from ..algo import location_bucket as _algo_location_bucket


def location_bucket(loc) -> str:
    """'remote' / city / region / country tokens. Single implementation in
    algo.py; this module is the public identity-facing entry point."""
    return _algo_location_bucket(loc)
