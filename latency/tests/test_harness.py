"""Tests for the templated beat loop latency spike.

The harness measures wall-clock time, so the tests deliberately do **not**
assert specific millisecond bounds — those vary by hardware and would make the
suite flaky in CI. Instead the tests pin the *behaviors* the measurement and
the report depend on:

* the percentile helper computes nearest-rank percentiles correctly on
  hand-checkable inputs,
* the harness produces the expected sample count and a verdict that flows from
  the samples (over_budget exactly when median or p95 exceeds the budget),
* the markdown report changes shape on the verdict (mentions the
  pre-generate/cache plan when over budget; says "Not needed" otherwise),
* the rendered report is byte-stable for a given report (no clock or RNG
  leaks into the format itself), and
* the templated beat loop is fast enough that 1 trial × 14 beats completes
  inside a generous wall-clock bound — a smoke check that the harness itself
  is not pathological.
"""

from __future__ import annotations

import json
import time

import pytest

from latency.__main__ import main as cli_main
from latency.harness import (
    DEFAULT_TRIALS,
    LATENCY_BUDGET_MS,
    BeatLatencyReport,
    _percentile,
    measure_beat_latency,
    render_report,
)
from game.act1 import load_act1_world


def test_percentile_nearest_rank_known_inputs() -> None:
    # 100 samples, integer-valued: nearest-rank with ceil → q=0.95 → index 95
    # (1-based), i.e. the 95th smallest sample.
    samples = list(range(1, 101))
    assert _percentile(samples, 0.50) == 50
    assert _percentile(samples, 0.95) == 95
    assert _percentile(samples, 1.0) == 100
    assert _percentile(samples, 0.0) == 1


def test_percentile_handles_unordered_input() -> None:
    samples = [5, 1, 4, 2, 3]
    # ceil(5 * 0.95) = 5 → the max
    assert _percentile(samples, 0.95) == 5.0
    # median by nearest-rank with ceil: ceil(5 * 0.5) = 3 → the 3rd smallest
    assert _percentile(samples, 0.5) == 3.0


def test_percentile_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        _percentile([], 0.5)
    with pytest.raises(ValueError):
        _percentile([1, 2, 3], -0.1)
    with pytest.raises(ValueError):
        _percentile([1, 2, 3], 1.5)


def test_measure_beat_latency_sample_shape() -> None:
    # 2 trials × 14 beats = 28 samples; cheap to run in CI.
    report = measure_beat_latency(trials=2, seed=42)

    world_length = load_act1_world().length
    assert report.beats_per_trial == world_length
    assert report.trials == 2
    assert report.n == 2 * world_length
    assert len(report.samples_ns) == report.n
    # All samples are positive monotonic-clock measurements.
    assert all(s > 0 for s in report.samples_ns)
    # Percentiles fall inside the observed range.
    assert report.min_ms <= report.median_ms <= report.max_ms
    assert report.min_ms <= report.p95_ms <= report.max_ms
    assert report.median_ms <= report.p95_ms


def test_measure_beat_latency_rejects_zero_trials() -> None:
    with pytest.raises(ValueError):
        measure_beat_latency(trials=0)


def test_over_budget_follows_samples_not_clock() -> None:
    # Construct two reports by hand so the test is independent of wall-clock
    # jitter: one whose p95 sits at the budget, one whose p95 exceeds it.
    inside = BeatLatencyReport(
        samples_ns=tuple(range(1_000_000, 21_000_000, 1_000_000)),  # 1–20 ms
        trials=1,
        beats_per_trial=20,
        budget_ms=150.0,
    )
    # Top 10% over budget — at n=20, nearest-rank p95 = sample 19 (ceil(20·0.95))
    # which is one of the 200 ms samples, so the verdict flips to over-budget.
    outside = BeatLatencyReport(
        samples_ns=tuple([1_000_000] * 18 + [200_000_000] * 2),
        trials=1,
        beats_per_trial=20,
        budget_ms=150.0,
    )
    assert inside.over_budget is False
    assert outside.over_budget is True


def test_render_report_under_budget_says_no_plan_needed() -> None:
    report = BeatLatencyReport(
        samples_ns=tuple(range(1_000_000, 21_000_000, 1_000_000)),
        trials=1,
        beats_per_trial=20,
        budget_ms=150.0,
    )
    rendered = render_report(report)
    assert "Within budget" in rendered
    assert "Not needed" in rendered
    # The TL;DR carries the exact ms numbers and the budget.
    assert f"{report.median_ms:.3f} ms" in rendered
    assert f"{report.p95_ms:.3f} ms" in rendered
    assert "150 ms" in rendered


def test_render_report_over_budget_emits_plan() -> None:
    report = BeatLatencyReport(
        samples_ns=tuple([200_000_000] * 20),  # all 200 ms beats
        trials=1,
        beats_per_trial=20,
        budget_ms=150.0,
    )
    rendered = render_report(report)
    assert "OVER BUDGET" in rendered
    assert "Pre-generate / cache plan (budget missed)" in rendered
    # The plan enumerates the four mitigations.
    assert "Pre-generate the per-beat content" in rendered
    assert "Cache the offer" in rendered
    assert "Hoist the system-voice template render" in rendered
    assert "identity transform" in rendered


def test_render_report_is_deterministic_for_fixed_report() -> None:
    # Same inputs → byte-identical output. This guards against the report
    # accidentally embedding a wall-clock timestamp or non-deterministic
    # iteration order (sets, dicts pre-3.7, etc.).
    report = BeatLatencyReport(
        samples_ns=tuple(range(1_000_000, 21_000_000, 1_000_000)),
        trials=1,
        beats_per_trial=20,
        budget_ms=150.0,
        seed=42,
    )
    assert render_report(report) == render_report(report)


def test_to_dict_round_trips_through_json() -> None:
    report = measure_beat_latency(trials=2, seed=42)
    data = report.to_dict()
    # JSON-serializable as-is.
    text = json.dumps(data, sort_keys=True)
    restored = json.loads(text)
    assert restored["n"] == report.n
    assert restored["trials"] == report.trials
    assert restored["beats_per_trial"] == report.beats_per_trial
    assert restored["samples_ns"] == list(report.samples_ns)
    assert restored["median_ms"] == report.median_ms
    assert restored["p95_ms"] == report.p95_ms
    assert restored["over_budget"] == report.over_budget


def test_cli_markdown_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(["--trials", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Templated Beat Loop — Latency Spike (M1)" in out
    assert "## Distribution" in out


def test_cli_json_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(["--trials", "1", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["trials"] == 1
    assert data["beats_per_trial"] == load_act1_world().length
    assert data["n"] == data["trials"] * data["beats_per_trial"]


def test_templated_beat_loop_is_well_inside_budget() -> None:
    # Wall-clock measurement, so the assertion is intentionally loose: we are
    # only catching pathological regressions (a beat that takes hundreds of
    # milliseconds). The committed report claims median + p95 well below
    # 150 ms; if either pokes above 50 ms here, something has gone wrong.
    #
    # 3 trials × ~14 beats is enough to compute p95 honestly while keeping the
    # test snappy in CI.
    report = measure_beat_latency(trials=3, seed=42)
    assert report.median_ms < 50.0, (
        f"templated beat median {report.median_ms} ms is unexpectedly slow"
    )
    assert report.p95_ms < 50.0, (
        f"templated beat p95 {report.p95_ms} ms is unexpectedly slow"
    )
    assert report.over_budget is False


def test_harness_does_not_dominate_wall_clock() -> None:
    # 1 trial of the templated beat loop must finish quickly — generous bound,
    # catches a regression that would make this spike unusable in CI.
    start = time.perf_counter()
    measure_beat_latency(trials=1, seed=42)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"latency harness took {elapsed:.2f}s for 1 trial"


def test_defaults_documented() -> None:
    # The two constants exposed on the package surface are the ones the report
    # and the acceptance criterion both quote; pin them so a casual rename
    # cannot silently disagree with the committed report.
    assert DEFAULT_TRIALS == 50
    assert LATENCY_BUDGET_MS == 150.0
