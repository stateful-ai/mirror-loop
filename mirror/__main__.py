"""``python -m mirror`` — the mirror-loop CLI.

Two subcommands, kept deliberately thin:

* ``schema`` (the default when no subcommand is given) — print the
  inferred-attribute schema and run the coherence review. Exit 0 when coherent,
  1 otherwise. Same behavior the module always had; preserved so the existing
  schema gate keeps working when called as ``python -m mirror``.
* ``play`` — drive one full mirror-loop session deterministically and write the
  gate-shaped session log as JSON to stdout. ``--seed`` picks a scripted persona
  reproducibly (and seeds any seam variant that consumes a seed); ``--baseline``
  flips the **shared adaptation seam** (:mod:`game.variants`) to the identity
  transform so the same engine plays the non-adaptive control arm. There is no
  forked "baseline" code path: the variant object is the only thing that
  differs, and the session runner calls it through the same offer/record path
  as the adaptive arm (see ``docs/THESIS.md`` and the architecture note in
  :mod:`game.variants`).
"""

from __future__ import annotations

import argparse
import json
import random

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


def _run_schema() -> int:
    print(
        f"Mirror player-state schema v{SCHEMA_VERSION} — "
        f"{len(MIRROR_SCHEMA)} inferred axes"
    )
    print(f"fingerprint: {schema_fingerprint()}\n")
    for name, spec in MIRROR_SCHEMA.items():
        print(f"  {name}")
        print(
            f"    kind={spec.kind.value}  dynamics={spec.dynamics.value}  "
            f"lr={spec.learning_rate}  decay/turn={spec.decay_per_turn}"
        )
        print(f"    {_shape(spec)}")
        print(f"    {spec.description}")
        print()
    report = coherence_report()
    print(report.render())
    return 0 if report.ok else 1


def _run_play(seed: int, baseline: bool) -> int:
    # Imported lazily so `python -m mirror schema` (and `--help`) stay free of
    # the game package's import cost and keep the schema gate isolated from the
    # runtime/replay layer.
    from game.session import PERSONAS, play_session
    from game.variants import build_variant

    # Seed picks the scripted persona deterministically. The same seed always
    # reproduces the same session byte-for-byte (the persona is pure, the engine
    # is deterministic, and the variant — even the placebo, if it were selected
    # — is seeded by this same value).
    persona_names = sorted(PERSONAS)
    persona = random.Random(seed).choice(persona_names)
    policy = PERSONAS[persona]()

    # The single A/B toggle: --baseline flips the shared adaptation seam to the
    # identity transform ("fixed"). The session runner calls the variant's
    # select_scene / order_choices identically for every arm; only the variant
    # object differs (game/variants.py).
    variant = build_variant("fixed" if baseline else "adaptive", seed=seed)

    session = play_session(policy, variant=variant)
    print(json.dumps(session.session_log(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mirror",
        description=(
            "Mirror Loop CLI. Default action (no subcommand): print the player-"
            "state schema and run the coherence review."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    subparsers.add_parser(
        "schema",
        help="print the player-state schema and run the coherence review",
        description=(
            "Print the inferred-attribute schema and run the anti-mush coherence "
            "review. Exit 0 when coherent, 1 otherwise."
        ),
    )

    play = subparsers.add_parser(
        "play",
        help="play one session and emit the gate-shaped JSON session log",
        description=(
            "Play one mirror-loop session deterministically and write the "
            "gate-shaped session log as JSON to stdout. --baseline flips the "
            "shared adaptation seam to the identity transform — no second "
            "code path; see game.variants."
        ),
    )
    play.add_argument(
        "--seed",
        type=int,
        default=0,
        help=(
            "RNG seed (default: 0). Picks the scripted persona deterministically "
            "and is forwarded to the adaptation seam variant; the same seed "
            "reproduces the same session."
        ),
    )
    play.add_argument(
        "--baseline",
        action="store_true",
        help=(
            "Flip the shared adaptation seam to the identity transform (the "
            "non-adaptive A/B control). Same engine and same code path as the "
            "adaptive arm; only the variant object differs."
        ),
    )

    args = parser.parse_args(argv)

    if args.command == "play":
        return _run_play(seed=args.seed, baseline=args.baseline)
    # Default (None) and explicit "schema" both run the schema gate.
    return _run_schema()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
