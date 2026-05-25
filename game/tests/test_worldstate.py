"""Tests for WorldState — the world position as a pure reduction over the log.

These guard the same architecture contract the Mirror reducer does, on the world
side: the event log is the source of truth, the position is a *pure reduction*
over it, the fold is deterministic, it round-trips through JSON, and a corrupt or
wrongly-versioned log fails loudly rather than yielding a quietly-wrong position.
"""

from __future__ import annotations

import pytest

from mirror.log import ChoiceObserved, EventLog, TurnAdvanced, log_from_choices
from mirror.state import Choice, Signal

from game.world import DEFAULT_WORLD, Slot, World
from game.worldstate import WORLDSTATE_SCHEMA_VERSION, VisitedSlot, WorldState


def _choice(scene_id: str, choice_id: str = "c") -> ChoiceObserved:
    return ChoiceObserved(choice_id=choice_id, scene_id=scene_id)


# The five slot keys of the default spine, in order.
_SPINE = ("intake", "records", "corridor", "confrontation", "exit")


# --- empty / partial / full reductions ----------------------------------------


def test_empty_log_reduces_to_the_start():
    state = WorldState.reduce(DEFAULT_WORLD, [])
    assert state.position == 0
    assert state.visited == ()
    assert not state.is_complete(DEFAULT_WORLD)
    assert state.next_slot_key(DEFAULT_WORLD) == "intake"
    assert state.world_name == DEFAULT_WORLD.name


def test_partial_log_tracks_position_and_next_slot():
    events = [_choice("intake", "c_reassure"), _choice("records", "c_close")]
    state = WorldState.reduce(DEFAULT_WORLD, events)
    assert state.position == 2
    assert [v.slot_key for v in state.visited] == ["intake", "records"]
    assert [v.choice_id for v in state.visited] == ["c_reassure", "c_close"]
    assert not state.is_complete(DEFAULT_WORLD)
    assert state.next_slot_key(DEFAULT_WORLD) == "corridor"


def test_full_spine_reduces_to_complete():
    events = [_choice(key) for key in _SPINE]
    state = WorldState.reduce(DEFAULT_WORLD, events)
    assert state.position == DEFAULT_WORLD.length == 5
    assert state.is_complete(DEFAULT_WORLD)
    assert state.next_slot_key(DEFAULT_WORLD) is None


def test_turn_advanced_events_do_not_move_the_world():
    # The interleaved decay events log_from_choices emits must not advance the
    # spine — only the choices do.
    log = log_from_choices(
        [
            Choice("a", signals=(Signal.toward("curiosity", 1.0),)),
            Choice("b", signals=(Signal.toward("curiosity", 1.0),)),
        ]
    )
    assert any(isinstance(e, TurnAdvanced) for e in log.events)
    state = WorldState.reduce(DEFAULT_WORLD, log.events)
    assert state.position == 2  # two choices, regardless of the TurnAdvanced events


def test_reduce_uses_spine_key_when_event_has_no_scene_id():
    # Mirror choice events carry scene_id only optionally; the reduction still
    # tracks position and labels each visited slot from the spine.
    state = WorldState.reduce(DEFAULT_WORLD, [ChoiceObserved("c1"), ChoiceObserved("c2")])
    assert [v.slot_key for v in state.visited] == ["intake", "records"]


# --- determinism & purity -----------------------------------------------------


def test_reduce_is_deterministic_and_pure():
    events = (_choice("intake"), _choice("records"))
    a = WorldState.reduce(DEFAULT_WORLD, events)
    b = WorldState.reduce(DEFAULT_WORLD, events)
    assert a == b
    assert events == (_choice("intake"), _choice("records"))  # inputs untouched


# --- loud failure on corrupt / overrun logs -----------------------------------


def test_overrunning_the_spine_raises():
    events = [_choice(key) for key in _SPINE] + [_choice("intake")]
    with pytest.raises(ValueError, match="overran"):
        WorldState.reduce(DEFAULT_WORLD, events)


def test_scene_id_disagreeing_with_the_slot_raises():
    # scene_id present but pointing at the wrong slot => recorded against another
    # world; refuse rather than silently mislabel.
    with pytest.raises(ValueError, match="different world spine"):
        WorldState.reduce(DEFAULT_WORLD, [_choice("corridor")])  # slot 0 is intake


def test_reduce_works_against_a_smaller_custom_world():
    tiny = World(name="tiny", slots=(Slot("only", fixed=DEFAULT_WORLD.slots[0].fixed),))
    state = WorldState.reduce(tiny, [_choice("only")])
    assert state.is_complete(tiny)
    with pytest.raises(ValueError, match="overran"):
        WorldState.reduce(tiny, [_choice("only"), _choice("only")])


# --- serialization round-trip & version guard ---------------------------------


def test_round_trips_through_json():
    state = WorldState.reduce(DEFAULT_WORLD, [_choice("intake", "c_reassure")])
    restored = WorldState.from_json(state.to_json())
    assert restored == state
    assert restored.visited == (VisitedSlot("intake", "c_reassure"),)


def test_to_dict_is_stamped_with_the_schema_version():
    state = WorldState.reduce(DEFAULT_WORLD, [])
    assert state.to_dict()["schema_version"] == WORLDSTATE_SCHEMA_VERSION


def test_from_dict_refuses_an_unknown_version():
    data = WorldState.reduce(DEFAULT_WORLD, []).to_dict()
    data["schema_version"] = WORLDSTATE_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="schema version"):
        WorldState.from_dict(data)


def test_from_dict_rejects_position_visited_mismatch():
    data = WorldState.reduce(DEFAULT_WORLD, [_choice("intake")]).to_dict()
    data["position"] = 5  # lie about the position
    with pytest.raises(ValueError, match="position"):
        WorldState.from_dict(data)


def test_reduces_over_an_eventlog_too():
    # The same container the Mirror reduces from also drives the world position.
    log = EventLog(events=(_choice("intake"), _choice("records")))
    assert WorldState.reduce(DEFAULT_WORLD, log.events).position == 2
