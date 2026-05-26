"""CLI for the templated beat loop latency spike — ``python -m latency``.

Walks the Act 1 templated beat loop ``--trials`` times, records every per-beat
wall-clock latency, and prints either the markdown report committed to
``docs/latency_report_m1.md`` or its JSON form. No flags needed for the
acceptance-criterion run — defaults reproduce the committed report on the
current machine.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .harness import (
    DEFAULT_TRIALS,
    LATENCY_BUDGET_MS,
    measure_beat_latency,
    render_report,
)
from game.act1 import DEFAULT_SEED


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m latency", description=__doc__
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=DEFAULT_TRIALS,
        help=f"number of full Act 1 walks to time (default {DEFAULT_TRIALS}). "
        "Each walk emits one sample per beat (~14 beats per walk).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"seed for the deterministic policy walk (default {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--budget-ms",
        type=float,
        default=LATENCY_BUDGET_MS,
        help=f"latency budget for median + p95, in milliseconds "
        f"(default {LATENCY_BUDGET_MS:.0f})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON instead of markdown",
    )
    args = parser.parse_args(argv)

    report = measure_beat_latency(
        trials=args.trials, seed=args.seed, budget_ms=args.budget_ms
    )

    if args.json:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render_report(report) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
