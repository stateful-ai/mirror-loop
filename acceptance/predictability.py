"""Beats-Baseline Prediction Test — the locked Mirror Loop acceptance gate.

See ``docs/THESIS.md`` for the thesis this enforces and the rationale for the
thresholds. This module is the single executable source of truth for whether a
session passes the gate.

The gate, in one line: at Act 2 decision points, the player model's top
prediction must match the player's actual choice **>= 60%** of the time **and**
beat the "always guess the player's most-frequent action" baseline by **>= 15
percentage points**. The margin gate is what stops a merely repetitive player
from looking "predicted."

Run it against a session log::

    python -m acceptance.predictability acceptance/fixtures/passing_session.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# --- Thresholds (the gate). Kept here as the single source of truth; mirrored in
# --- docs/THESIS.md §2. Moving these requires founder re-approval.
MIN_TOP1_ACCURACY = 0.60
MIN_MARGIN_OVER_BASELINE = 0.15
MIN_DECISION_POINTS = 5  # too few points to score reliably -> FAIL, not PASS.


@dataclass(frozen=True)
class DecisionPoint:
    """One Act 2 decision: what the model predicted vs. what the player did.

    ``predicted_actions`` is the model's ranked forecast, highest confidence
    first. An empty forecast is allowed and simply counts as a miss.
    """

    predicted_actions: tuple[str, ...]
    actual_action: str

    @property
    def top1_correct(self) -> bool:
        return bool(self.predicted_actions) and self.predicted_actions[0] == self.actual_action


@dataclass(frozen=True)
class AcceptanceResult:
    passed: bool
    top1_accuracy: float
    baseline_accuracy: float
    margin: float
    n: int
    reason: str

    def render(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"[{verdict}] Beats-Baseline Prediction Test\n"
            f"  decision points : {self.n}\n"
            f"  top-1 accuracy  : {self.top1_accuracy:.3f} (gate >= {MIN_TOP1_ACCURACY:.2f})\n"
            f"  baseline acc    : {self.baseline_accuracy:.3f} (most-frequent-action)\n"
            f"  margin          : {self.margin:+.3f} (gate >= {MIN_MARGIN_OVER_BASELINE:.2f})\n"
            f"  reason          : {self.reason}"
        )


def top1_accuracy(points: Sequence[DecisionPoint]) -> float:
    """Fraction of decision points where the model's top guess was right."""
    if not points:
        return 0.0
    return sum(p.top1_correct for p in points) / len(points)


def baseline_accuracy(points: Sequence[DecisionPoint]) -> float:
    """Accuracy of the trivial 'always guess this player's most-frequent action'.

    This is the bar the model must clear: predicting that a player will simply
    repeat their single most common behavior. Ties are broken by frequency only
    (any most-frequent action gives the same accuracy).
    """
    if not points:
        return 0.0
    actuals = [p.actual_action for p in points]
    most_common_count = Counter(actuals).most_common(1)[0][1]
    return most_common_count / len(actuals)


def evaluate(points: Sequence[DecisionPoint]) -> AcceptanceResult:
    """Apply the locked gate to a sequence of Act 2 decision points."""
    n = len(points)
    acc = top1_accuracy(points)
    base = baseline_accuracy(points)
    margin = acc - base

    if n < MIN_DECISION_POINTS:
        return AcceptanceResult(
            passed=False,
            top1_accuracy=acc,
            baseline_accuracy=base,
            margin=margin,
            n=n,
            reason=f"insufficient data: {n} decision points (need >= {MIN_DECISION_POINTS})",
        )

    meets_accuracy = acc >= MIN_TOP1_ACCURACY
    meets_margin = margin >= MIN_MARGIN_OVER_BASELINE
    passed = meets_accuracy and meets_margin

    if passed:
        reason = "model beats baseline by a real margin: player is predictable and modelled"
    elif not meets_accuracy and not meets_margin:
        reason = "below accuracy floor and no margin over baseline"
    elif not meets_accuracy:
        reason = "top-1 accuracy below floor: player not predictable enough"
    else:
        reason = "margin below floor: model only rides the most-frequent-action baseline"

    return AcceptanceResult(
        passed=passed,
        top1_accuracy=acc,
        baseline_accuracy=base,
        margin=margin,
        n=n,
        reason=reason,
    )


def load_session(path: str | Path) -> list[DecisionPoint]:
    """Load Act 2 decision points from a session log JSON file.

    Expected shape::

        {
          "session_id": "...",
          "act": "act_2",
          "decision_points": [
            {"predicted_actions": ["a", "b", "c"], "actual_action": "a"},
            ...
          ]
        }
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_points = data["decision_points"]
    return [
        DecisionPoint(
            predicted_actions=tuple(dp.get("predicted_actions", [])),
            actual_action=dp["actual_action"],
        )
        for dp in raw_points
    ]


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: python -m acceptance.predictability <session.json>", file=sys.stderr)
        return 2
    result = evaluate(load_session(argv[0]))
    print(result.render())
    return 0 if result.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
