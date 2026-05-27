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
* ``validate-fixture FILE [--strict]`` — statically validate an intake-answers
  JSON fixture against the current questionnaire schema. Prints ``OK`` on
  stdout and exits 0 on success; prints the first error on stderr and exits 1
  on a malformed fixture; exits 2 when the path is missing (so a CI lint can
  tell "fixture wrong" from "fixture not found" without parsing the message).
  ``--strict`` also checks that every option the answers reference exists in
  the schema today. Backed by :mod:`mirror.validate`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mirror.play import run as run_play_intake
from mirror.schema import (
    MIRROR_SCHEMA,
    SCHEMA_VERSION,
    AttributeKind,
    coherence_report,
    schema_fingerprint,
)
from mirror.validate import validate_fixture


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


def _run_validate_fixture(args: argparse.Namespace) -> int:
    """Validate one fixture file.

    Exit codes:

    * ``0`` — fixture is valid; prints ``OK`` on stdout.
    * ``1`` — fixture is present but malformed; prints the first error on stderr.
    * ``2`` — path does not exist; prints the first error on stderr. The separate
      code lets a CI lint distinguish "fixture wrong" from "fixture not found"
      without parsing the message.
    """
    # Missing-path is promoted to its own exit code here (not inside
    # ``validate_fixture``) so the library function can keep returning a uniform
    # structured result for every failure mode while the CLI surface still gives
    # a CI lint a clean signal to branch on.
    if not Path(args.fixture).exists():
        print(f"fixture file {args.fixture!r} not found", file=sys.stderr)
        return 2
    result = validate_fixture(args.fixture, strict=args.strict)
    if result.ok:
        print("OK")
        return 0
    # Errors go to stderr so a caller redirecting stdout to /dev/null still sees
    # why validation failed, matching the convention `play` already follows for
    # its prompts.
    print(result.error, file=sys.stderr)
    return 1


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

    vf = subparsers.add_parser(
        "validate-fixture",
        help=(
            "check an intake-answers JSON fixture's shape + semantics against "
            "the current questionnaire schema; prints OK or the first error"
        ),
    )
    vf.add_argument(
        "fixture",
        type=str,
        metavar="FILE",
        help=(
            "path to the answers fixture (a flat JSON object mapping "
            "question_id -> answer_id, the same shape `play --answers` reads)"
        ),
    )
    vf.add_argument(
        "--strict",
        action="store_true",
        help=(
            "also require that every option the answers reference exists in "
            "the schema today (catches a fixture written against an older or "
            "removed answer option). Default behavior already rejects unknown "
            "answer ids; --strict is here for the API surface a future "
            "stricter check (e.g. full questionnaire required) plugs into."
        ),
    )
    vf.set_defaults(_handler=_run_validate_fixture)

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
