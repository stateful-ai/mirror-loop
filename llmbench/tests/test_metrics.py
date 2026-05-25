"""The percentile and mean primitives behind every published number."""

from __future__ import annotations

import pytest

from llmbench.metrics import mean, percentile


def test_percentile_known_values_linear_interpolation():
    xs = [1, 2, 3, 4]
    assert percentile(xs, 0) == 1
    assert percentile(xs, 100) == 4
    assert percentile(xs, 50) == pytest.approx(2.5)  # median of an even count
    # Rank 0.95*(4-1)=2.85 -> between xs[2]=3 and xs[3]=4.
    assert percentile(xs, 95) == pytest.approx(3.85)


def test_percentile_is_order_independent():
    assert percentile([4, 1, 3, 2], 50) == percentile([1, 2, 3, 4], 50)


def test_percentile_single_value():
    assert percentile([7.0], 50) == 7.0
    assert percentile([7.0], 95) == 7.0


def test_percentile_never_extrapolates():
    xs = list(range(101))  # 0..100
    p = percentile(xs, 95)
    assert min(xs) <= p <= max(xs)
    assert percentile(xs, 50) == pytest.approx(50)


def test_p95_at_least_p50_for_a_spread_sample():
    xs = [1, 1, 1, 5, 9, 9, 100]
    assert percentile(xs, 95) >= percentile(xs, 50)


def test_percentile_rejects_empty_and_out_of_range():
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1, 2], -1)
    with pytest.raises(ValueError):
        percentile([1, 2], 101)


def test_mean():
    assert mean([2, 4, 6]) == pytest.approx(4.0)
    with pytest.raises(ValueError):
        mean([])
