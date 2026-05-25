"""CLI for the cost/latency harness — ``python -m llmbench``.

By default this runs the **offline** sweep (the :class:`~llmbench.client.SimulatedClient`):
exact cost, modeled latency, deterministic in ``(--seed, --trials)`` so the numbers
in ``docs/LLM_COST_LATENCY.md`` regenerate by running it with the defaults.

``--live`` runs the **live latency spike** instead — the same sweep against the real
endpoint via :class:`~llmbench.client.LiveClient`, reporting *measured* wall-clock
latency and provider-reported token usage. It needs ``ANTHROPIC_API_KEY`` and makes
real (billable) network calls, so keep ``--trials`` small and optionally pin one
``--model``. A live run is not deterministic; that is the point.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from .client import LiveClient
from .harness import DEFAULT_SEED, DEFAULT_TRIALS, measure, render_report
from .models import CANDIDATE_MODELS, get_model


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m llmbench", description=__doc__
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=DEFAULT_TRIALS,
        help=f"latency samples per prompt (default {DEFAULT_TRIALS}; "
        "use a small value with --live to keep the spike short and cheap)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"run seed; fixes the modeled latency jitter (default {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON instead of markdown",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="measure real latency against the live endpoint (needs ANTHROPIC_API_KEY; "
        "makes billable calls). Default is the offline simulator.",
    )
    parser.add_argument(
        "--model",
        action="append",
        metavar="NAME",
        help="restrict the sweep to this candidate model (repeatable); "
        "defaults to all candidates. Useful to keep a --live spike small.",
    )
    args = parser.parse_args(argv)

    try:
        models = (
            tuple(get_model(name) for name in args.model)
            if args.model
            else CANDIDATE_MODELS
        )
    except ValueError as exc:
        parser.error(str(exc))

    client = None
    if args.live:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            parser.error("--live requires ANTHROPIC_API_KEY in the environment")
        client = LiveClient(api_key=api_key)

    report = measure(
        models=models, trials=args.trials, seed=args.seed, client=client
    )

    if args.json:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render_report(report) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
