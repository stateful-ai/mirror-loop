"""Tests for ``python -m mirror dump-events``.

The subcommand is a *debug view* over a saved event log: read JSON, print one
line per event in the form ``<turn>\\t<type>\\t<payload-summary>``. These
tests pin the contract:

- the turn counter increments on each :class:`TurnAdvanced`, so a choice in
  turn 0 prints with ``0`` and a choice after the first decay prints with ``1``
  (matching ``MirrorState.turn``);
- ``--type`` filters in both spellings (class name + wire discriminator), and
  the filter does not desync the turn counter;
- ``--json`` round-trips one event per line as a JSON object with the same
  ``turn`` annotation;
- a missing or malformed log fails loudly with a non-zero exit code instead of
  spraying a traceback.
"""

from __future__ import annotations

import io
import json

import pytest

from mirror.__main__ import iter_dump_lines, main
from mirror.log import (
    ChoiceObserved,
    EventLog,
    TurnAdvanced,
)
from mirror.state import Signal


def _sample_log() -> EventLog:
    """Three turns of evidence — enough to exercise turn boundaries + filters."""
    return EventLog(
        events=(
            # turn 0
            ChoiceObserved(
                choice_id="question",
                signals=(
                    Signal.toward("authority_trust", -1.0),
                    Signal.spend("playstyle_mix", "conversation"),
                ),
                scene_id="opening",
                act_id="act_i",
            ),
            TurnAdvanced(),
            # turn 1
            ChoiceObserved(
                choice_id="inspect_exit",
                signals=(Signal.toward("boundary_testing", 1.0, weight=0.5),),
            ),
            TurnAdvanced(),
            # turn 2 — choice with no signals (an inert observation)
            ChoiceObserved(choice_id="wait"),
        )
    )


def test_dump_events_human_readable_turn_and_type_columns():
    """Each line is ``<turn>\\t<wire-type>\\t<payload>`` and turns advance on tick."""
    lines = list(iter_dump_lines(_sample_log()))
    assert len(lines) == 5

    # Tab-separated, three columns.
    parsed = [line.split("\t", 2) for line in lines]
    turns = [p[0] for p in parsed]
    types = [p[1] for p in parsed]
    payloads = [p[2] for p in parsed]

    # The TurnAdvanced that *closes* turn 0 still prints with turn 0; the next
    # ChoiceObserved (in turn 1) is the first row to print "1".
    assert turns == ["0", "0", "1", "1", "2"]
    assert types == [
        "choice_observed",
        "turn_advanced",
        "choice_observed",
        "turn_advanced",
        "choice_observed",
    ]

    # Payload summaries carry the actually-useful debug info.
    assert "choice=question" in payloads[0]
    assert "scene=opening" in payloads[0]
    assert "act=act_i" in payloads[0]
    assert "authority_trust=-1" in payloads[0]
    assert "playstyle_mix=spend:conversation" in payloads[0]
    assert payloads[1] == "(decay tick)"
    # Weight != 1.0 surfaces as @0.5.
    assert "boundary_testing=+1@0.5" in payloads[2]
    # Empty-signal choice still parses, and is labeled as such.
    assert "signals=[]" in payloads[4]


def test_dump_events_type_filter_accepts_both_spellings_and_keeps_turn_counting():
    """``--type`` accepts class name + wire form; filter doesn't desync turns."""
    log = _sample_log()

    by_class = list(iter_dump_lines(log, type_filter="choice_observed"))
    # Equivalent via class-name resolution (verified through the CLI handler in
    # the integration test below).
    assert len(by_class) == 3
    # Filtered output should still report the *correct* turn for each kept
    # event — the TurnAdvanceds we suppressed still moved the counter.
    turns = [line.split("\t", 1)[0] for line in by_class]
    assert turns == ["0", "1", "2"]

    # Filtering to turn_advanced gives only the decay rows.
    only_ticks = list(iter_dump_lines(log, type_filter="turn_advanced"))
    assert len(only_ticks) == 2
    assert all("turn_advanced" in line for line in only_ticks)
    assert [line.split("\t", 1)[0] for line in only_ticks] == ["0", "1"]


def test_dump_events_json_mode_emits_one_object_per_line_with_turn():
    """``--json`` is one event dict per line, annotated with the turn it ran in."""
    log = _sample_log()
    lines = list(iter_dump_lines(log, as_json=True))
    assert len(lines) == 5

    parsed = [json.loads(line) for line in lines]
    # The event_type discriminator + turn field are present on every row.
    assert [p["event_type"] for p in parsed] == [
        "choice_observed",
        "turn_advanced",
        "choice_observed",
        "turn_advanced",
        "choice_observed",
    ]
    assert [p["turn"] for p in parsed] == [0, 0, 1, 1, 2]

    # The signals payload survives round-tripping through event_to_dict.
    assert parsed[0]["signals"][0] == {
        "attribute": "authority_trust",
        "target": -1.0,
        "weight": 1.0,
    }


def test_dump_events_cli_handles_missing_file_and_unknown_type(tmp_path, capsys):
    """Operator errors get a clean message + exit 2, not a Python traceback."""
    # A path that does not exist.
    rc = main(["dump-events", str(tmp_path / "no-such-log.json")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot read" in err

    # A valid log file, but a bogus --type value.
    log_path = tmp_path / "log.json"
    log_path.write_text(_sample_log().to_json(), encoding="utf-8")
    rc = main(["dump-events", str(log_path), "--type", "NotARealEvent"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown event type" in err

    # Class-name spelling actually resolves and produces output. (This is the
    # integration with the CLI parser that the in-process test above does not
    # cover.)
    rc = main(["dump-events", str(log_path), "--type", "ChoiceObserved"])
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 3
    assert all("choice_observed" in line for line in out)


def test_dump_events_cli_rejects_malformed_log(tmp_path, capsys):
    """A log that isn't valid JSON exits 2 with a clear error, not a traceback."""
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not valid json", encoding="utf-8")
    rc = main(["dump-events", str(bad)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot parse event log" in err
