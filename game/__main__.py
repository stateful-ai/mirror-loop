"""``python -m game`` — play one Mirror Loop session, with no LLM.

Usage::

    python -m game                  # play interactively (read choices from stdin)
    python -m game --demo           # watch a scripted "kind" persona play
    python -m game --persona NAME   # scripted: kind | controlling | defiant | erratic
    python -m game --log [--persona NAME]   # emit the gate-shaped session log as JSON

The demo/persona modes are fully deterministic, which is what makes the whole
game reproducible and testable without a human or a model in the loop.
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


def _play(persona: str | None, *, quiet: bool = False) -> tuple[Session, bool]:
    """Return the played session and whether it was interactive.

    With ``quiet`` set (``--log``), the interactive prompts and the Mirror's live
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
        return play_session(policy, on_loop=on_loop), True
    if persona not in PERSONAS:
        raise SystemExit(
            f"unknown persona {persona!r}; choose one of: {', '.join(sorted(PERSONAS))}"
        )
    return play_session(PERSONAS[persona]()), False


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
    args = parser.parse_args(argv)

    persona = args.persona
    if args.demo and persona is None:
        persona = "kind"

    try:
        session, interactive = _play(persona, quiet=args.log)
    except EOFError:
        # Interactive play with no input available (e.g. `python -m game
        # </dev/null`): fall back to the deterministic demo so the command still
        # shows the loop end to end.
        print("(no input available — running the 'kind' demo persona)\n", file=sys.stderr)
        session, interactive = _play("kind")

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
