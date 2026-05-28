"""Tests for the Mirror as a pure reducer over a recorded event log.

These guard the architecture contract: the event log is the source of truth and
the player-state is a *pure reduction* over it. Concretely —

- a fresh/empty log reduces to a blank mirror that knows nothing;
- reducing is deterministic: the same log always yields the same state, and that
  state equals driving :class:`MirrorState` imperatively with the same actions;
- a log round-trips through JSON and the restored log reduces to identical state;
- the schema version + fingerprint stamped on a log gate replay, so a log from a
  drifted schema is refused rather than silently mis-reduced.

Coverage spans empty, short, and full (multi-act) sessions.
"""

from __future__ import annotations

import copy
import json

import pytest

from mirror.schema import MIRROR_SCHEMA, SCHEMA_VERSION, AttributeKind, schema_fingerprint
from mirror.state import Choice, MirrorState, Signal
from mirror.log import (
    ChoiceObserved,
    EventLog,
    TurnAdvanced,
    event_from_dict,
    event_to_dict,
    log_from_choices,
    reduce,
)


# --- session fixtures: empty, short, full -------------------------------------


def _short_session() -> list[Choice]:
    """Two turns of evidence — enough to move axes, not enough to be confident."""
    return [
        Choice("question", signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "conversation"),
        )),
        Choice("inspect_exit", signals=(
            Signal.toward("boundary_testing", 1.0),
            Signal.spend("playstyle_mix", "exploration"),
            Signal.toward("frustration", 1.0, weight=0.5),
        )),
    ]


def _full_session() -> list[Choice]:
    """A long, multi-act session: a defiant, cautious, system-probing player."""
    return [
        Choice("question", signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "conversation"),
        )),
        Choice("inspect_exit", signals=(
            Signal.toward("boundary_testing", 1.0),
            Signal.spend("playstyle_mix", "exploration"),
            Signal.toward("frustration", 1.0, weight=0.6),
        )),
        Choice("refuse_risky_offer", signals=(Signal.toward("risk_tolerance", -1.0),)),
        Choice("challenge", signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "conversation"),
        )),
        Choice("probe_again", signals=(Signal.toward("boundary_testing", 1.0),)),
        Choice("decline_again", signals=(Signal.toward("risk_tolerance", -1.0),)),
        Choice("read_lore", signals=(
            Signal.toward("curiosity", 1.0),
            Signal.spend("playstyle_mix", "exploration"),
        )),
        Choice("hold_principle", signals=(Signal.toward("moral_consistency", 1.0),)),
    ]


def _apply_imperatively(choices: list[Choice]) -> MirrorState:
    """The reference path: drive a state by hand, one choice + tick per turn."""
    state = MirrorState.new()
    for choice in choices:
        state.apply_choice(choice)
        state.tick()
    return state


# --- empty session -------------------------------------------------------------


def test_empty_log_reduces_to_a_blank_mirror():
    state = reduce([])
    assert state == MirrorState.new()
    assert set(state.readings) == set(MIRROR_SCHEMA)
    for name, reading in state.readings.items():
        assert reading.confidence == 0.0, name
        assert reading.evidence_count == 0.0, name
    assert state.known() == {}  # nothing is known until the log says so


def test_empty_eventlog_reduces_to_blank_and_round_trips():
    log = EventLog()
    assert log.schema_version == SCHEMA_VERSION
    assert log.reduce() == MirrorState.new()
    restored = EventLog.from_json(log.to_json())
    assert restored.reduce() == MirrorState.new()


# --- short session -------------------------------------------------------------


def test_short_session_matches_the_imperative_path():
    choices = _short_session()
    from_log = log_from_choices(choices).reduce()
    by_hand = _apply_imperatively(choices)
    assert from_log == by_hand


def test_short_session_moves_only_what_was_signaled():
    state = log_from_choices(_short_session()).reduce()
    # Signaled axes moved off neutral...
    assert state.readings["authority_trust"].value < 0.0
    assert state.readings["boundary_testing"].value > 0.5
    # ...and an axis nothing signaled is still unknown at its neutral.
    assert state.readings["risk_tolerance"].value == 0.0
    assert state.readings["risk_tolerance"].confidence == 0.0


def test_short_session_frustration_decayed_via_turn_events():
    # frustration spiked on turn 2 then the TurnAdvanced after it relaxed it,
    # so the recorded log's reduction shows it below the raw spike.
    spike = MIRROR_SCHEMA["frustration"].learning_rate * 0.5  # weight 0.5
    state = log_from_choices(_short_session()).reduce()
    assert 0.0 < state.readings["frustration"].value < spike


# --- full session --------------------------------------------------------------


def test_full_session_produces_a_differentiated_profile():
    state = log_from_choices(_full_session()).reduce()
    assert state.readings["authority_trust"].value < -0.2  # defiant
    assert state.readings["risk_tolerance"].value < -0.1  # cautious
    assert state.readings["boundary_testing"].value > 0.55  # probes the system
    mix = state.readings["playstyle_mix"].value
    spec = MIRROR_SCHEMA["playstyle_mix"]
    assert mix[spec.modes.index("combat")] == min(mix)  # never fought

    scalar_values = [
        state.readings[n].value
        for n, s in MIRROR_SCHEMA.items()
        if s.kind is not AttributeKind.DISTRIBUTION
    ]
    assert max(scalar_values) - min(scalar_values) > 0.5  # not mush


def test_full_session_matches_the_imperative_path():
    choices = _full_session()
    assert log_from_choices(choices).reduce() == _apply_imperatively(choices)


# --- determinism ---------------------------------------------------------------


def test_reduce_is_deterministic():
    log = log_from_choices(_full_session())
    a = log.reduce()
    b = log.reduce()
    assert a == b
    assert a.snapshot() == b.snapshot()
    # And reducing a separately-constructed identical log agrees too.
    assert reduce(log.events) == a


def test_reduction_is_pure_does_not_mutate_the_log():
    log = log_from_choices(_short_session())
    before = log.to_dict()
    log.reduce()
    assert log.to_dict() == before  # the log is untouched by reducing it


# --- scan: the running reductions ---------------------------------------------


def test_scan_yields_state_after_each_event_and_ends_at_reduce():
    log = log_from_choices(_short_session())
    states = list(log.scan())
    assert len(states) == len(log.events)
    assert states[-1] == log.reduce()


def test_scan_snapshots_are_independent_copies():
    # Each yielded state must be a true snapshot, not a live reference to the
    # final state — so reconstructing "the Mirror as of turn t" is sound.
    log = log_from_choices(_full_session())
    states = list(log.scan())
    early = copy.deepcopy(states[0].snapshot())
    # The first ChoiceObserved touches authority_trust; later events do too. If
    # snapshots aliased, states[0] would already show the later value.
    assert states[0].snapshot() == early
    assert states[0].readings["authority_trust"].value != states[-1].readings[
        "authority_trust"
    ].value


# --- serialization round-trip --------------------------------------------------


def test_full_log_round_trips_through_json_to_identical_state():
    log = log_from_choices(_full_session())
    restored = EventLog.from_json(log.to_json())
    assert restored.events == log.events
    assert restored.reduce() == log.reduce()
    assert restored.reduce().snapshot() == log.reduce().snapshot()


def test_to_json_is_sorted_and_stable():
    log = log_from_choices(_short_session())
    assert log.to_json() == log.to_json()  # stable
    parsed = json.loads(log.to_json())
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["fingerprint"] == schema_fingerprint()
    assert isinstance(parsed["events"], list)


def test_choice_event_round_trips_with_signals_and_provenance():
    event = ChoiceObserved(
        choice_id="inspect_exit_under_pressure",
        signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "exploration"),
            Signal.toward("frustration", 1.0, weight=0.5),
        ),
        scene_id="lab_observation_room",
        act_id="act_2",
    )
    restored = event_from_dict(event_to_dict(event))
    assert restored == event


def test_turn_event_round_trips():
    assert event_from_dict(event_to_dict(TurnAdvanced())) == TurnAdvanced()


def test_choice_event_omits_empty_provenance_in_serialized_form():
    data = event_to_dict(ChoiceObserved("c"))
    assert "scene_id" not in data and "act_id" not in data
    assert data["event_type"] == ChoiceObserved.EVENT_TYPE
    assert data["signals"] == []


def test_unknown_event_type_is_rejected_on_deserialize():
    with pytest.raises(ValueError):
        event_from_dict({"event_type": "telepathy"})


def test_from_choice_and_as_choice_are_inverse():
    choice = Choice("c", signals=(Signal.toward("curiosity", 1.0),))
    assert ChoiceObserved.from_choice(choice).as_choice() == choice


# --- the schema-version / fingerprint guard -----------------------------------


def test_reduce_refuses_a_log_from_a_different_schema_version():
    log = EventLog(events=(TurnAdvanced(),), schema_version=SCHEMA_VERSION + 1)
    with pytest.raises(ValueError, match="schema version"):
        log.reduce()


def test_reduce_refuses_a_log_with_a_mismatched_fingerprint():
    # Same version, but the structural fingerprint disagrees -> the schema
    # changed without a version bump, so recomputation would silently differ.
    log = EventLog(events=(TurnAdvanced(),), fingerprint="deadbeef")
    with pytest.raises(ValueError, match="fingerprint"):
        log.reduce()


def test_round_tripped_log_preserves_version_and_fingerprint():
    log = log_from_choices(_short_session())
    restored = EventLog.from_json(log.to_json())
    assert restored.schema_version == log.schema_version
    assert restored.fingerprint == log.fingerprint
    restored.reduce()  # current schema -> still reducible


def test_from_dict_without_fingerprint_is_refused_at_reduce():
    # A log persisted without a fingerprint can't be proven to match the schema,
    # so it is rejected rather than reduced on faith.
    log = log_from_choices(_short_session())
    data = log.to_dict()
    del data["fingerprint"]
    restored = EventLog.from_dict(data)
    with pytest.raises(ValueError, match="fingerprint"):
        restored.reduce()


# --- corrupt logs fail loudly --------------------------------------------------


def test_a_malformed_signal_in_the_log_raises_rather_than_being_absorbed():
    log = EventLog(events=(
        ChoiceObserved("bad", signals=(Signal.toward("not_an_axis", 1.0),)),
    ))
    with pytest.raises(KeyError):
        log.reduce()


def test_out_of_range_target_in_the_log_is_rejected():
    log = EventLog(events=(
        ChoiceObserved("bad", signals=(Signal.toward("curiosity", 2.0),)),
    ))
    with pytest.raises(ValueError):
        log.reduce()


# --- append is non-mutating ----------------------------------------------------


def test_append_returns_a_new_log_and_leaves_the_original_alone():
    base = EventLog()
    extended = base.append(ChoiceObserved("c"), TurnAdvanced())
    assert base.events == ()
    assert len(extended.events) == 2
    assert extended.schema_version == base.schema_version
    assert extended.fingerprint == base.fingerprint
