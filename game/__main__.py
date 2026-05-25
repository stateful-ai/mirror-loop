"""``python -m game`` — play one Mirror Loop session, with no LLM.

Usage::

    python -m game                  # play interactively (read choices from stdin)
    python -m game --demo           # watch a scripted "kind" persona play
    python -m game --persona NAME   # scripted: kind | controlling | defiant | erratic
    python -m game --log [--persona NAME]   # emit the gate-shaped session log as JSON
    python -m game --variant fixed  # play a non-adaptive baseline arm (A/B control)
    python -m game --variant random --seed N   # the seeded placebo baseline

``--variant`` is the single A/B toggle (``adaptive`` | ``fixed`` | ``random``):
the same engine and shell, with the adaptation seam set to the real player model,
the identity transform, or a player-independent placebo (see ``game.variants``).
The demo/persona modes — and the seeded placebo — are fully deterministic, which
is what makes the whole game reproducible and testable without a human or a model
in the loop.
"""

from __future__ import annotations

import argparse
import json
import sys

from .session import (
    PERSONAS,
    Session,
    live_feedback,
    play_session,
    report_block,
    stdin_policy,
    transcript,
)
from .variants import VARIANT_NAMES, Variant, build_variant


def _eprint(text: str) -> None:
    """Write interactive chatter to stderr, keeping stdout for machine output."""
    print(text, file=sys.stderr)


def _stderr_input(prompt: str) -> str:
    """Like ``input`` but write the prompt to stderr, so stdout stays clean.

    Raises ``EOFError`` at end of input, matching ``input`` so the caller's
    no-input fallback still fires.
    """
    print(prompt, end="", file=sys.stderr, flush=True)
    line = sys.stdin.readline()
    if line == "":
        raise EOFError
    return line.rstrip("\n")


def _play(
    persona: str | None, *, variant: Variant, quiet: bool = False
) -> tuple[Session, bool]:
    """Return the played session and whether it was interactive.

    ``variant`` is the A/B arm; it is threaded through unchanged so every mode
    (interactive, demo, persona) can be played against any baseline. With
    ``quiet`` set (``--log``), the interactive prompts and the Mirror's live
    reactions are routed to stderr so stdout carries only the JSON session log.
    """
    if persona is None:
        # Interactive: a real player drives the choices and sees the Mirror react
        # live between them (so we don't re-print the whole transcript after).
        if quiet:
            policy = stdin_policy(prompt=_stderr_input, out=_eprint)
            on_loop = live_feedback(out=_eprint)
        else:
            policy = stdin_policy()
            on_loop = live_feedback()
        return play_session(policy, variant=variant, on_loop=on_loop), True
    if persona not in PERSONAS:
        raise SystemExit(
            f"unknown persona {persona!r}; choose one of: {', '.join(sorted(PERSONAS))}"
        )
    return play_session(PERSONAS[persona](), variant=variant), False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m game", description=__doc__)
    parser.add_argument(
        "--persona",
        choices=sorted(PERSONAS),
        help="play a scripted persona instead of reading choices from stdin",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="shorthand for --persona kind",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="print the gate-compatible session log as JSON instead of the transcript",
    )
    parser.add_argument(
        "--variant",
        choices=VARIANT_NAMES,
        default="adaptive",
        help="the A/B arm: 'adaptive' (real game), 'fixed' (identity baseline), "
        "or 'random' (seeded placebo baseline). Default: adaptive.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="RNG seed for '--variant random' (deterministic; default 0). Ignored otherwise.",
    )
    args = parser.parse_args(argv)

    variant = build_variant(args.variant, seed=args.seed)

    persona = args.persona
    if args.demo and persona is None:
        persona = "kind"

    try:
        session, interactive = _play(persona, variant=variant, quiet=args.log)
    except EOFError:
        # Interactive play with no input available (e.g. `python -m game
        # </dev/null`): fall back to the deterministic demo so the command still
        # shows the loop end to end — on the same variant the player asked for.
        print("(no input available — running the 'kind' demo persona)\n", file=sys.stderr)
        session, interactive = _play("kind", variant=variant)

    if args.log:
        print(json.dumps(session.session_log(), indent=2))
    elif interactive:
        # The player already watched the session unfold; just show the readout.
        print("\n" + report_block(session))
    else:
        print(transcript(session))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
