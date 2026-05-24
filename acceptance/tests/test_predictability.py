"""Tests for the Beats-Baseline Prediction Test (the locked acceptance gate).

These verify two things: (1) the evaluator's math and gate logic are correct,
and (2) the two committed fixtures land on the right side of the gate, so the
gate is demonstrably *discriminating* — it passes a modelled player and fails a
player the baseline already nails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from acceptance.predictability import (
    MIN_DECISION_POINTS,
    MIN_MARGIN_OVER_BASELINE,
    MIN_TOP1_ACCURACY,
    DecisionPoint,
    baseline_accuracy,
    evaluate,
    load_session,
    main,
    top1_accuracy,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def dp(actual: str, *predicted: str) -> DecisionPoint:
    return DecisionPoint(predicted_actions=tuple(predicted), actual_action=actual)


# --- metric units --------------------------------------------------------------


def test_top1_accuracy_counts_only_top_prediction():
    points = [dp("a", "a", "b"), dp("b", "a", "b"), dp("c", "c", "a")]
    # correct on point 0 and 2 -> 2/3
    assert top1_accuracy(points) == pytest.approx(2 / 3)


def test_top1_empty_prediction_is_a_miss():
    assert top1_accuracy([dp("a")]) == 0.0


def test_baseline_is_most_frequent_action_share():
    points = [dp("a"), dp("a"), dp("a"), dp("b"), dp("c")]
    assert baseline_accuracy(points) == pytest.approx(0.6)


def test_metrics_on_empty_input_are_zero():
    assert top1_accuracy([]) == 0.0
    assert baseline_accuracy([]) == 0.0


# --- gate logic ----------------------------------------------------------------


def test_fails_when_margin_too_small_even_if_accurate():
    # Player almost always does 'a'; model just predicts 'a'. Accuracy hits the
    # floor but the dumb baseline matches it -> no margin -> FAIL.
    points = [dp("a", "a") for _ in range(6)] + [
        dp("b", "a"),
        dp("c", "a"),
        dp("d", "a"),
        dp("e", "a"),
    ]
    result = evaluate(points)
    assert result.top1_accuracy == pytest.approx(0.6)
    assert result.baseline_accuracy == pytest.approx(0.6)
    assert result.margin == pytest.approx(0.0)
    assert not result.passed
    assert "margin" in result.reason


def test_fails_when_below_accuracy_floor_even_with_margin():
    # Diverse actuals (baseline low) but model only right 4/10 -> below floor.
    actuals = ["a", "b", "c", "d", "e", "a", "b", "c", "d", "e"]
    points = [dp(a, "a") for a in actuals]  # always predicts 'a'
    result = evaluate(points)
    assert result.top1_accuracy == pytest.approx(0.2)
    assert result.baseline_accuracy == pytest.approx(0.2)
    assert not result.passed


def test_clean_pass_with_low_baseline_and_high_accuracy():
    # Diverse actuals (baseline 0.2) and model right 7/10 -> margin 0.5 -> PASS.
    actuals = ["a", "b", "c", "d", "e", "a", "b", "c", "d", "e"]
    preds = ["a", "b", "c", "d", "e", "a", "b", "x", "y", "z"]
    points = [dp(a, p) for a, p in zip(actuals, preds)]
    result = evaluate(points)
    assert result.top1_accuracy == pytest.approx(0.7)
    assert result.baseline_accuracy == pytest.approx(0.2)
    assert result.margin == pytest.approx(0.5)
    assert result.passed


def test_insufficient_decision_points_fails_closed():
    points = [dp("a", "a")] * (MIN_DECISION_POINTS - 1)
    result = evaluate(points)
    assert not result.passed
    assert "insufficient data" in result.reason


def test_thresholds_are_the_locked_values():
    # Guard against silent threshold drift away from docs/THESIS.md §2.
    assert MIN_TOP1_ACCURACY == 0.60
    assert MIN_MARGIN_OVER_BASELINE == 0.15
    assert MIN_DECISION_POINTS == 5


# --- fixtures: the gate must discriminate -------------------------------------


def test_passing_fixture_passes():
    result = evaluate(load_session(FIXTURES / "passing_session.json"))
    assert result.passed, result.render()
    assert result.top1_accuracy == pytest.approx(0.7)
    assert result.baseline_accuracy == pytest.approx(0.4)
    assert result.margin == pytest.approx(0.3)


def test_failing_fixture_fails():
    result = evaluate(load_session(FIXTURES / "failing_session.json"))
    assert not result.passed, result.render()
    assert result.top1_accuracy == pytest.approx(0.6)
    assert result.baseline_accuracy == pytest.approx(0.6)
    assert result.margin == pytest.approx(0.0)


# --- CLI -----------------------------------------------------------------------


def test_cli_returns_zero_on_pass_and_one_on_fail(capsys):
    assert main([str(FIXTURES / "passing_session.json")]) == 0
    assert main([str(FIXTURES / "failing_session.json")]) == 1
    out = capsys.readouterr().out
    assert "PASS" in out and "FAIL" in out


def test_cli_usage_error_without_arg():
    assert main([]) == 2
