"""Pins the v0 adaptation decision (``docs/ADAPTATION.md``) to the code.

The decision doc names exactly one adaptation type (*tendency mirroring*), the one
axis it reads (*dominant tendency*), three concrete example adaptations, and the
boundary that keeps the type contained. These tests assert each of those claims
against the real ``Mirror.adapt`` (in-scene re-ordering) and ``Slot.pick``
(across-scene framing selection) so the doc cannot quietly drift from the engine.
"""

from __future__ import annotations

from loop.core import Mirror, PlayerState, Scene

from game.world import (
    CONFRONTATION,
    DEFAULT_WORLD,
    INTAKE,
    dominant_tendency,
)

# Real Choice objects, one per tendency, lifted from the world's intake scene.
_BY_TENDENCY = {c.tendency: c for c in INTAKE.choices}


def _lean(*tendencies: str) -> PlayerState:
    """A player state whose history leans the given tendencies (via real scenes)."""
    state = PlayerState()
    for i, tendency in enumerate(tendencies):
        choice = _BY_TENDENCY[tendency]
        scene = Scene(id=f"s{i}", prompt="", choices=(choice,))
        state = state.record(scene, choice)
    return state


def _slot(key: str):
    slot = next(s for s in DEFAULT_WORLD.slots if s.key == key)
    return slot


# --- §3.1  In-scene re-ordering: a kindness player at `confrontation` -----------


def test_confrontation_declares_the_kind_option_last():
    # The example only demonstrates re-ordering because the kind option starts
    # last; pin that premise so the example stays honest.
    assert CONFRONTATION.choices[-1].id == "c_wait"
    assert CONFRONTATION.choices[-1].tendency == "kindness"


def test_kindness_player_has_c_wait_surfaced_first():
    state = _lean("kindness", "kindness", "kindness")
    offered = Mirror().adapt(state, CONFRONTATION)
    assert offered.choices[0].id == "c_wait"


def test_re_ordering_preserves_the_exact_choice_set():
    # §4.1: the adaptation only orders — it never invents, drops, or rewrites.
    state = _lean("kindness", "kindness", "kindness")
    declared = CONFRONTATION
    offered = Mirror().adapt(state, declared)
    assert {c.id for c in offered.choices} == {c.id for c in declared.choices}
    by_id = {c.id: c for c in declared.choices}
    for c in offered.choices:
        assert c.text == by_id[c.id].text  # prose untouched, order only


# --- §3.2  Across-scene selection: a control player at `records` ----------------


def test_control_player_is_shown_the_control_framing_at_records():
    records = _slot("records")
    assert dominant_tendency(_lean("control", "control")) == "control"
    scene, key = records.pick(_lean("control", "control"))
    assert key == "control"
    assert scene is records.variants["control"]
    assert "metrics overlay you never asked for" in scene.prompt


# --- §3.3  Across-scene selection: a defiance player at `exit` ------------------


def test_defiance_player_is_shown_the_defiant_framing_at_exit():
    exit_slot = _slot("exit")
    assert dominant_tendency(_lean("defiance", "defiance", "defiance")) == "defiance"
    scene, key = exit_slot.pick(_lean("defiance", "defiance", "defiance"))
    assert key == "defiance"
    assert scene is exit_slot.variants["defiance"]
    assert "Prove you are not predictable" in scene.prompt


# --- §2 / §4.4  Reads one axis; no lean -> identity transform -------------------


def test_no_history_is_an_identity_transform_in_scene():
    # With no observed lean the in-scene surface is a no-op (declared order kept).
    offered = Mirror().adapt(PlayerState(), CONFRONTATION)
    assert [c.id for c in offered.choices] == [c.id for c in CONFRONTATION.choices]


def test_no_history_falls_back_to_neutral_framing_across_scenes():
    records = _slot("records")
    scene, key = records.pick(PlayerState())
    assert key == "default"
    assert scene is records.variants["default"]


def test_top_tie_is_no_lean_so_neutral_framing_is_shown():
    # The axis is read as a strict argmax for selection: an exact top tie is not a
    # lean, so the Mirror does not guess.
    assert dominant_tendency(_lean("kindness", "control")) is None
    scene, key = _slot("records").pick(_lean("kindness", "control"))
    assert key == "default"


def test_surfaced_option_depends_only_on_the_dominant_tendency():
    # §2: only the dominant tendency feeds the adaptation. Two kindness-dominant
    # states with different secondary counts both surface the same lead option.
    a = Mirror().adapt(_lean("kindness", "kindness", "kindness"), CONFRONTATION)
    b = Mirror().adapt(_lean("kindness", "kindness", "kindness", "control"), CONFRONTATION)
    assert a.choices[0].id == b.choices[0].id == "c_wait"
