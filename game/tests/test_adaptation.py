"""Tests for the Adaptation schema.

The load-bearing acceptance contract: **every Adaptation records its trigger
Mirror snapshot and its source event-seq**, and it does so structurally — there
is no way to build one without that provenance. The rest pins the schema down:
the snapshot faithfully reads the v0 one-axis Mirror, the two surfaces are
constrained to their own output shapes, and the whole thing is versioned and
round-trips through JSON.
"""

from __future__ import annotations

import pytest

from loop.core import Choice, PlayerState, Turn

from game.adaptation import (
    ADAPTATION_SCHEMA_VERSION,
    Adaptation,
    AdaptationKind,
    AdaptationLog,
    AdaptationProvenance,
    MirrorSnapshot,
)
from game.world import dominant_tendency


def _state(*tendencies: str) -> PlayerState:
    """A PlayerState whose history expresses ``tendencies`` in order."""
    history = tuple(
        Turn(scene_id=f"s{i}", choice=Choice(f"c{i}", "text", tendency, "did a thing"))
        for i, tendency in enumerate(tendencies)
    )
    return PlayerState(history=history)


# --- MirrorSnapshot: a faithful read of the v0 one-axis Mirror ----------------


def test_snapshot_captures_counts_and_dominant():
    state = _state("kindness", "kindness", "control")
    snap = MirrorSnapshot.from_player_state(state)
    assert snap.turn_count == 3
    assert dict(snap.tendency_counts) == {"kindness": 2, "control": 1}
    assert snap.dominant == "kindness" == dominant_tendency(state)


def test_snapshot_counts_are_sorted_for_a_stable_serialized_form():
    snap = MirrorSnapshot.from_player_state(_state("defiance", "control", "kindness"))
    names = [name for name, _ in snap.tendency_counts]
    assert names == sorted(names)


def test_snapshot_dominant_is_none_on_a_tie_matching_the_adaptation_rule():
    state = _state("kindness", "control")  # 1–1 tie at the top
    snap = MirrorSnapshot.from_player_state(state)
    assert snap.dominant is None == dominant_tendency(state)


def test_snapshot_of_an_empty_state_is_blank():
    snap = MirrorSnapshot.from_player_state(PlayerState())
    assert snap.turn_count == 0
    assert snap.tendency_counts == ()
    assert snap.dominant is None


# --- the acceptance contract: provenance is recorded, always ------------------


def test_branch_selection_records_trigger_snapshot_and_event_seq():
    state = _state("control", "control")
    adaptation = Adaptation.branch_selection(
        "records", "control", state=state, source_event_seq=2
    )
    prov = adaptation.provenance
    assert prov.source_event_seq == 2
    assert prov.trigger_snapshot.dominant == "control"
    assert prov.trigger_snapshot.turn_count == 2


def test_choice_reordering_records_trigger_snapshot_and_event_seq():
    state = _state("kindness", "kindness", "kindness")
    adaptation = Adaptation.choice_reordering(
        "confrontation", ("c_wait", "c_walk", "c_log"), state=state, source_event_seq=3
    )
    prov = adaptation.provenance
    assert prov.source_event_seq == 3
    assert prov.trigger_snapshot.dominant == "kindness"
    assert adaptation.predicted_choice == "c_wait"


def test_provenance_is_a_required_field_of_every_adaptation():
    # Constructing an Adaptation requires a provenance positionally/by keyword;
    # there is no default, so an un-provenanced adaptation cannot exist.
    with pytest.raises(TypeError):
        Adaptation(  # type: ignore[call-arg]
            kind=AdaptationKind.BRANCH_SELECTION,
            slot_key="records",
            revealed="control",
            ordering=(),
        )


def test_event_seq_equals_turn_count_in_the_v0_one_choice_per_loop_runtime():
    state = _state("defiance", "defiance")
    adaptation = Adaptation.branch_selection(
        "exit", "defiance", state=state, source_event_seq=state.turn_count
    )
    assert adaptation.provenance.source_event_seq == adaptation.provenance.trigger_snapshot.turn_count


def test_negative_event_seq_is_rejected():
    with pytest.raises(ValueError, match="source_event_seq"):
        AdaptationProvenance(
            source_event_seq=-1, trigger_snapshot=MirrorSnapshot(turn_count=0)
        )


# --- the two surfaces are constrained to their own output shapes ---------------


def test_branch_selection_must_set_revealed_and_no_ordering():
    prov = AdaptationProvenance(0, MirrorSnapshot(turn_count=0))
    with pytest.raises(ValueError, match="revealed"):
        Adaptation(AdaptationKind.BRANCH_SELECTION, "s", None, (), prov)
    with pytest.raises(ValueError, match="ordering"):
        Adaptation(AdaptationKind.BRANCH_SELECTION, "s", "control", ("a",), prov)


def test_choice_reordering_must_set_ordering_and_no_revealed():
    prov = AdaptationProvenance(0, MirrorSnapshot(turn_count=0))
    with pytest.raises(ValueError, match="revealed"):
        Adaptation(AdaptationKind.CHOICE_REORDERING, "s", "control", ("a",), prov)
    with pytest.raises(ValueError, match="ordering"):
        Adaptation(AdaptationKind.CHOICE_REORDERING, "s", None, (), prov)


def test_predicted_choice_is_none_for_a_branch_selection():
    a = Adaptation.branch_selection("records", "control", state=_state("control"), source_event_seq=1)
    assert a.predicted_choice is None


# --- serialization round-trip & versioning ------------------------------------


def test_adaptation_round_trips_through_dict():
    state = _state("kindness", "kindness", "kindness")
    for adaptation in (
        Adaptation.branch_selection("exit", "kindness", state=state, source_event_seq=3),
        Adaptation.choice_reordering(
            "confrontation", ("c_wait", "c_log", "c_walk"), state=state, source_event_seq=3
        ),
    ):
        assert Adaptation.from_dict(adaptation.to_dict()) == adaptation


def test_snapshot_and_provenance_round_trip():
    snap = MirrorSnapshot.from_player_state(_state("control", "defiance", "control"))
    assert MirrorSnapshot.from_dict(snap.to_dict()) == snap
    prov = AdaptationProvenance(source_event_seq=3, trigger_snapshot=snap)
    assert AdaptationProvenance.from_dict(prov.to_dict()) == prov


def test_adaptation_log_round_trips_through_json():
    state = _state("control")
    log = AdaptationLog().append(
        Adaptation.branch_selection("records", "control", state=state, source_event_seq=1),
        Adaptation.choice_reordering(
            "records", ("c_read", "c_close", "c_breach"), state=state, source_event_seq=1
        ),
    )
    restored = AdaptationLog.from_json(log.to_json())
    assert restored == log
    assert restored.to_dict()["schema_version"] == ADAPTATION_SCHEMA_VERSION


def test_adaptation_log_append_is_non_mutating():
    base = AdaptationLog()
    extended = base.append(
        Adaptation.branch_selection("records", "control", state=_state("control"), source_event_seq=1)
    )
    assert base.adaptations == ()
    assert len(extended.adaptations) == 1


def test_adaptation_log_refuses_an_unknown_version():
    data = AdaptationLog().to_dict()
    data["schema_version"] = ADAPTATION_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="schema version"):
        AdaptationLog.from_dict(data)
