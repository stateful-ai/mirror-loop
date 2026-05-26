"""``python -m mirror`` — Mirror CLI: schema review and the play entrypoint.

Subcommands:

* (no args) / ``schema`` — print the inferred-attribute schema and the
  coherence report. Exit code is 0 when coherent, 1 otherwise. Preserved as the
  default so existing references to ``python -m mirror`` (README, docstrings,
  founder brief) keep working.
* ``play [--seed N] [--answers FILE]`` — run the questionnaire intake and emit
  the resulting :class:`~mirror.log.EventLog` as JSON on stdout. With
  ``--answers FILE`` the run is non-interactive and reads ``{question_id:
  answer_id}`` from a JSON file (the CI / fixture-capture mode); without it
  the run prompts on stderr and reads from stdin. Both modes feed the same
  :func:`mirror.intake.seed_log`, so the emitted log is byte-identical for a
  given answer set.
"""

from __future__ import annotations

import argparse
import sys

from mirror.play import run as run_play_intake
from mirror.schema import (
    MIRROR_SCHEMA,
    SCHEMA_VERSION,
    AttributeKind,
    coherence_report,
    schema_fingerprint,
)


def _shape(spec) -> str:
    if spec.kind is AttributeKind.DISTRIBUTION:
        return "{" + ", ".join(spec.modes) + "}"
    return f"{spec.poles[0]}  <->  {spec.poles[1]}"


def render_schema() -> int:
    """Print the schema table + coherence report. The original ``main`` behavior."""
    print(
        f"Mirror player-state schema v{SCHEMA_VERSION} — "
        f"{len(MIRROR_SCHEMA)} inferred axes"
    )
    print(f"fingerprint: {schema_fingerprint()}\n")
    for name, spec in MIRROR_SCHEMA.items():
        print(f"  {name}")
        print(f"    kind={spec.kind.value}  dynamics={spec.dynamics.value}  "
              f"lr={spec.learning_rate}  decay/turn={spec.decay_per_turn}")
        print(f"    {_shape(spec)}")
        print(f"    {spec.description}")
        print()
    report = coherence_report()
    print(report.render())
    return 0 if report.ok else 1


def _run_play(args: argparse.Namespace) -> int:
    log_json = run_play_intake(seed=args.seed, answers_path=args.answers)
    sys.stdout.write(log_json)
    if not log_json.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mirror", description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "schema",
        help="print the schema table and the coherence report (the default)",
    )

    play = subparsers.add_parser(
        "play",
        help="run the questionnaire intake and emit the resulting event log JSON",
    )
    play.add_argument(
        "--seed",
        type=int,
        default=0,
        help=(
            "RNG seed reserved for the play command's gameplay phase (default "
            "0). Intake is deterministic from the answers alone, so the seed "
            "does not affect the emitted intake log."
        ),
    )
    play.add_argument(
        "--answers",
        type=str,
        default=None,
        metavar="FILE",
        help=(
            "JSON file mapping question_id -> answer_id (docs/INTAKE.md §2). "
            "If set, the intake runs non-interactively with no TTY prompts — "
            "the mode CI and fixture capture use."
        ),
    )
    play.set_defaults(_handler=_run_play)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        # No subcommand (or the explicit ``schema``): preserve the historical
        # default so the documented ``python -m mirror`` keeps working.
        return render_schema()
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
