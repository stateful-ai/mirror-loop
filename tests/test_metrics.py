"""Pinned-behavior tests for :mod:`llmbench.metrics`.

These complement the in-package suite (``llmbench/tests/test_metrics.py``) by
asserting the exact, documented shape of the percentile/mean primitives from
the repo-root tests/: the linear-interpolation definition the module names in
its docstring, the empty-input contract, and the public ``__all__`` surface.
"""

from __future__ import annotations

import math

import pytest

from llmbench import metrics
from llmbench.metrics import mean, percentile


def test_public_api_surface():
    # The module is the auditable home of the percentile method behind every
    # published p50/p95 — pin the exported surface so a silent rename is caught.
    assert set(metrics.__all__) == {"mean", "percentile"}


def test_percentile_endpoints_return_min_and_max():
    xs = [10.0, 20.0, 30.0, 40.0]
    assert percentile(xs, 0) == 10.0
    assert percentile(xs, 100) == 40.0


def test_percentile_median_even_count_is_midpoint():
    # Linear interpolation of [1,2,3,4] at q=50: rank = 0.5*3 = 1.5 -> 2.5.
    assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)


def test_percentile_median_odd_count_is_middle_value():
    # Rank = 0.5*(5-1) = 2.0 -> integral rank, returns xs[2].
    assert percentile([1, 2, 3, 4, 5], 50) == 3.0


def test_percentile_linear_interpolation_matches_documented_formula():
    # Documented: rank = (q/100)*(n-1) and the result is interpolated between
    # the bracketing order statistics. With xs=[0,10] and q=37: rank=0.37,
    # frac=0.37, so result = 0 + (10 - 0) * 0.37 = 3.7.
    assert percentile([0.0, 10.0], 37) == pytest.approx(3.7)


def test_percentile_sorts_input_first():
    unsorted = [4, 1, 3, 2]
    ordered = [1, 2, 3, 4]
    for q in (0, 25, 50, 75, 95, 100):
        assert percentile(unsorted, q) == pytest.approx(percentile(ordered, q))


def test_percentile_single_value_returns_that_value():
    assert percentile([7.5], 0) == 7.5
    assert percentile([7.5], 50) == 7.5
    assert percentile([7.5], 100) == 7.5


def test_percentile_never_extrapolates_beyond_observed_range():
    xs = [-3.0, -1.0, 0.5, 2.0, 11.0]
    lo, hi = min(xs), max(xs)
    for q in (0, 1, 17, 50, 83, 99, 100):
        result = percentile(xs, q)
        assert lo <= result <= hi


def test_percentile_returns_float_even_for_integer_input():
    # Documented signature: -> float. Integer endpoints must still come back
    # as floats so downstream formatters don't have to special-case ints.
    result = percentile([1, 2, 3, 4], 0)
    assert isinstance(result, float)
    assert result == 1.0


def test_percentile_monotonic_in_q():
    xs = [1.0, 4.0, 9.0, 16.0, 25.0]
    qs = [0, 10, 25, 50, 75, 90, 100]
    values = [percentile(xs, q) for q in qs]
    assert values == sorted(values)


def test_percentile_accepts_tuple_input():
    # The annotation is Sequence[float]; tuples must work.
    assert percentile((1, 2, 3, 4), 50) == pytest.approx(2.5)


def test_percentile_q_zero_and_hundred_are_inclusive_boundary():
    # The documented range is [0, 100] — both endpoints are valid.
    percentile([1, 2], 0)
    percentile([1, 2], 100)


def test_percentile_rejects_q_out_of_range():
    with pytest.raises(ValueError, match=r"q must be in \[0, 100\]"):
        percentile([1, 2, 3], -0.0001)
    with pytest.raises(ValueError, match=r"q must be in \[0, 100\]"):
        percentile([1, 2, 3], 100.0001)


def test_percentile_rejects_nan_q():
    # NaN fails every ordered comparison, so the [0, 100] guard must reject it
    # rather than producing a silent NaN result.
    with pytest.raises(ValueError):
        percentile([1, 2, 3], float("nan"))


def test_percentile_rejects_empty_input():
    with pytest.raises(ValueError, match="empty sequence"):
        percentile([], 50)


def test_mean_basic():
    assert mean([2.0, 4.0, 6.0]) == pytest.approx(4.0)


def test_mean_single_value():
    assert mean([42.0]) == 42.0


def test_mean_uses_fsum_for_numerical_stability():
    # math.fsum is the documented summation primitive; mean must inherit its
    # exactness rather than reintroducing drift via a naive accumulator.
    values = [0.1] * 10
    assert mean(values) == math.fsum(values) / len(values)
    # And a classic-drift case where the unstable accumulator notably differs
    # from fsum: a long alternating tail of large and small magnitudes.
    drifty = [1e16, 1.0, -1e16, 1.0]
    assert mean(drifty) == math.fsum(drifty) / len(drifty)


def test_mean_handles_negative_and_mixed_signs():
    assert mean([-2.0, 0.0, 2.0]) == pytest.approx(0.0)
    assert mean([-1.0, -2.0, -3.0]) == pytest.approx(-2.0)


def test_mean_accepts_tuple_input():
    assert mean((1.0, 2.0, 3.0)) == pytest.approx(2.0)


def test_mean_rejects_empty_input():
    with pytest.raises(ValueError, match="empty sequence"):
        mean([])
