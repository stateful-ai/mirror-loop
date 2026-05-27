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
* ``dump-events FILE [--type=TYPE] [--json]`` — read a saved event log JSON
  and print one line per event in a human-readable form,
  ``<turn>  <type>  <payload-summary>``. The turn is the count of
  :class:`~mirror.log.TurnAdvanced` events seen *before* this one, so events
  emitted during turn ``t`` print with ``t`` (matching the in-game numbering
  ``MirrorState.turn``). ``--type=ChoiceObserved`` (also accepted: the wire
  form ``choice_observed``) filters to a single event type. ``--json`` switches
  output to one JSON object per line — the same dict
  :func:`~mirror.log.event_to_dict` produces, plus a ``turn`` field — useful
  when piping into ``jq``. The log itself is *not* reduced, so a log captured
  under a drifted schema is still inspectable for debugging.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Iterator

from mirror.log import (
    ChoiceObserved,
    EventLog,
    MirrorEvent,
    TurnAdvanced,
    event_to_dict,
)
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


# --- dump-events: human-readable view over a saved event log ------------------
#
# This is a debug view, not a replay. We deliberately go through
# ``EventLog.from_json`` (so an unknown event_type fails loudly with the same
# message the reducer would give) but *not* through ``EventLog.reduce``: a log
# captured under a drifted schema should still be inspectable so the operator
# can see what went wrong.


#: Canonical class name -> wire ``event_type`` discriminator. Built from the
#: event classes so adding a new event type (declaring its ``EVENT_TYPE``)
#: automatically picks it up for the ``--type`` filter.
_EVENT_TYPE_NAMES: dict[str, str] = {
    ChoiceObserved.__name__: ChoiceObserved.EVENT_TYPE,
    TurnAdvanced.__name__: TurnAdvanced.EVENT_TYPE,
}


def _resolve_type_filter(raw: str) -> str:
    """Translate a ``--type`` argument to a wire ``event_type`` discriminator.

    Accepts either the Python class name (``ChoiceObserved``) or the serialized
    form (``choice_observed``) so the flag matches whichever spelling the user
    has at hand. An unknown value raises so a typo fails loudly rather than
    silently filtering everything out.
    """
    wire_values = set(_EVENT_TYPE_NAMES.values())
    if raw in _EVENT_TYPE_NAMES:
        return _EVENT_TYPE_NAMES[raw]
    if raw in wire_values:
        return raw
    known = sorted(set(_EVENT_TYPE_NAMES) | wire_values)
    raise ValueError(f"unknown event type {raw!r}; known: {', '.join(known)}")


def _signal_summary(signal) -> str:
    """One signal as a compact ``attribute=…`` token for the human view."""
    if signal.mode is not None:
        body = f"{signal.attribute}=spend:{signal.mode}"
    elif signal.target is not None:
        body = f"{signal.attribute}={signal.target:+g}"
    else:
        body = signal.attribute
    if signal.weight != 1.0:
        body = f"{body}@{signal.weight:g}"
    return body


def _payload_summary(event: MirrorEvent) -> str:
    """Compact, one-line payload summary for the human-readable dump."""
    if isinstance(event, ChoiceObserved):
        parts: list[str] = [f"choice={event.choice_id}"]
        if event.scene_id is not None:
            parts.append(f"scene={event.scene_id}")
        if event.act_id is not None:
            parts.append(f"act={event.act_id}")
        if event.signals:
            parts.append(
                "signals=["
                + ", ".join(_signal_summary(s) for s in event.signals)
                + "]"
            )
        else:
            parts.append("signals=[]")
        return " ".join(parts)
    if isinstance(event, TurnAdvanced):
        return "(decay tick)"
    # Defensive: a new event type added later still gets a sensible dump.
    return repr(event)


def iter_dump_lines(
    log: EventLog,
    *,
    type_filter: str | None = None,
    as_json: bool = False,
) -> Iterator[str]:
    """Yield one rendered line per event in ``log``.

    ``type_filter`` is a wire ``event_type`` discriminator (or ``None`` for no
    filter); ``as_json=True`` swaps the human-readable line for the per-event
    dict serialized as JSON, with a ``turn`` field added so the output is still
    per-turn-addressable.

    The ``turn`` counter increments on each :class:`TurnAdvanced`, so events
    emitted *during* turn ``t`` (including the ``TurnAdvanced`` that closes it)
    print with ``t``. Exposed as a function rather than baked into the handler
    so tests can drive the rendering directly without spawning a subprocess.
    """
    turn = 0
    for event in log.events:
        wire_type = event_to_dict(event)["event_type"]
        emit = type_filter is None or wire_type == type_filter
        if emit:
            if as_json:
                payload = event_to_dict(event)
                payload["turn"] = turn
                yield json.dumps(payload, sort_keys=True)
            else:
                yield f"{turn}\t{wire_type}\t{_payload_summary(event)}"
        if isinstance(event, TurnAdvanced):
            turn += 1


def _run_dump_events(args: argparse.Namespace) -> int:
    try:
        type_filter = (
            _resolve_type_filter(args.type) if args.type is not None else None
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        with open(args.file, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        print(f"error: cannot read {args.file!r}: {exc}", file=sys.stderr)
        return 2
    try:
        log = EventLog.from_json(text)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: cannot parse event log: {exc}", file=sys.stderr)
        return 2
    for line in iter_dump_lines(log, type_filter=type_filter, as_json=args.json):
        sys.stdout.write(line + "\n")
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

    dump = subparsers.add_parser(
        "dump-events",
        help="read a saved event log JSON and print one line per event",
    )
    dump.add_argument(
        "file",
        metavar="FILE",
        help="path to a JSON event log written by, e.g., python -m mirror play",
    )
    dump.add_argument(
        "--type",
        type=str,
        default=None,
        metavar="TYPE",
        help=(
            "only print events of this type. Accepts the class name "
            "(e.g. ChoiceObserved) or the wire discriminator "
            "(e.g. choice_observed)."
        ),
    )
    dump.add_argument(
        "--json",
        action="store_true",
        help="emit each event as a JSON object (with a turn field) instead of text.",
    )
    dump.set_defaults(_handler=_run_dump_events)

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
