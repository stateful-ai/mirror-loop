"""Pure statistics for the harness: percentiles, with no numpy.

The acceptance bar names **p50 and p95** explicitly, so percentile estimation is a
load-bearing primitive — and the repo is stdlib-only. :func:`percentile` is the
linear-interpolation estimator (the same definition numpy calls ``"linear"`` and
the one most latency tooling reports), kept here so the percentile method behind
every published number is one auditable function rather than a hidden default.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q``-th percentile of ``values`` by linear interpolation.

    ``q`` is in ``[0, 100]``. With a single value that value is returned; with
    several, the rank ``(q/100)·(n-1)`` is interpolated between its bracketing
    order statistics — so ``percentile(xs, 50)`` is the median and the result is
    never an extrapolation beyond the observed range. Raises on empty input (a
    percentile of nothing is undefined, and silently returning 0 would be a lie).
    """
    if not 0.0 <= q <= 100.0:
        raise ValueError(f"q must be in [0, 100], got {q}")
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("percentile of an empty sequence is undefined")
    if n == 1:
        return float(ordered[0])
    rank = (q / 100.0) * (n - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean; raises on empty input."""
    if not values:
        raise ValueError("mean of an empty sequence is undefined")
    return math.fsum(values) / len(values)


__all__ = ["mean", "percentile"]
