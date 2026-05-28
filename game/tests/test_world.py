"""The handcrafted world: branch selection, agency preservation, fixed length.

These pin the second way the Mirror visibly drives content — choosing which
pre-authored framing to *reveal* from the player model (``docs/CORE_LOOP.md`` §2
is the in-scene re-ordering; this is the across-scene branch selection) — while
proving the player's agency is never reduced and the spine stays inside the
3–5-loop session target.
"""

from __future__ import annotations

from loop.core import PlayerState, Scene

from game.world import (
    DEFAULT_WORLD,
    TENDENCY_PRIORITY,
    Slot,
    dominant_tendency,
)

TENDENCIES = ("kindness", "control", "defiance")


def _state_with(*tendencies: str) -> PlayerState:
    """Build a state whose history leans the given tendencies, via real scenes."""
    state = PlayerState()
    for i, tendency in enumerate(tendencies):
        choice = next(c for c in DEFAULT_WORLD.slots[0].fixed.choices if c.tendency == tendency)
        scene = Scene(id=f"s{i}", prompt="", choices=(choice,))
        state = state.record(scene, choice)
    return state


# --- dominant_tendency: only tailors once the player has actually leaned --------


def test_dominant_tendency_is_none_with_no_history():
    assert dominant_tendency(PlayerState()) is None


def test_dominant_tendency_returns_clear_leader():
    assert dominant_tendency(_state_with("kindness", "kindness", "control")) == "kindness"


def test_dominant_tendency_is_none_on_a_top_tie():
    # An exact tie at the top is not a lean — the Mirror must fall back to neutral
    # framing rather than guessing, which keeps content selection honest.
    assert dominant_tendency(_state_with("kindness", "control")) is None


# --- Slot.pick: fixed vs. branch selection -------------------------------------


def test_fixed_slot_always_returns_its_scene():
    scene = DEFAULT_WORLD.slots[0].fixed
    slot = Slot("intake", fixed=scene)
    picked, key = slot.pick(_state_with("defiance", "defiance"))
    assert picked is scene
    assert key == "fixed"


def test_branch_slot_reveals_framing_for_the_dominant_tendency():
    records = DEFAULT_WORLD.slots[1]
    assert records.variants is not None
    picked, key = records.pick(_state_with("kindness", "kindness"))
    assert key == "kindness"
    assert picked is records.variants["kindness"]


def test_branch_slot_falls_back_to_default_when_no_lean():
    records = DEFAULT_WORLD.slots[1]
    picked, key = records.pick(PlayerState())  # no history -> no dominant
    assert key == "default"
    assert picked is records.variants["default"]


def test_branch_slot_falls_back_to_default_on_a_tie():
    records = DEFAULT_WORLD.slots[1]
    _, key = records.pick(_state_with("kindness", "control"))
    assert key == "default"


# --- The Mirror visibly drives content: different players see different rooms ---


def test_different_players_are_shown_different_framings():
    records = DEFAULT_WORLD.slots[1]
    kind_scene, _ = records.pick(_state_with("kindness"))
    control_scene, _ = records.pick(_state_with("control"))
    defy_scene, _ = records.pick(_state_with("defiance"))
    prompts = {kind_scene.prompt, control_scene.prompt, defy_scene.prompt}
    # Same dilemma, three distinct authored framings selected by the player model.
    assert len(prompts) == 3


# --- Agency is never reduced: every scene still offers all three tendencies -----


def _all_scenes() -> list[Scene]:
    scenes: list[Scene] = []
    for slot in DEFAULT_WORLD.slots:
        if slot.fixed is not None:
            scenes.append(slot.fixed)
        else:
            assert slot.variants is not None
            scenes.extend(slot.variants.values())
    return scenes


def test_every_scene_offers_all_three_tendencies():
    for scene in _all_scenes():
        offered = {c.tendency for c in scene.choices}
        assert offered == set(TENDENCIES), f"{scene.id} dropped a tendency: {offered}"


def test_every_scene_has_unique_choice_ids():
    for scene in _all_scenes():
        ids = [c.id for c in scene.choices]
        assert len(ids) == len(set(ids)), f"{scene.id} has duplicate choice ids"


def test_every_choice_carries_an_evidence_phrase():
    # The reflection beat cites only these pre-authored, in-fiction phrases.
    for scene in _all_scenes():
        for choice in scene.choices:
            assert choice.evidence, f"{scene.id}/{choice.id} has no evidence phrase"


# --- The spine: a fixed length inside the 3–5-loop target ----------------------


def test_default_world_is_a_five_loop_spine():
    assert DEFAULT_WORLD.length == 5
    assert 3 <= DEFAULT_WORLD.length <= 5


def test_world_slot_keys_are_the_expected_spine():
    keys = [slot.key for slot in DEFAULT_WORLD.slots]
    assert keys == ["intake", "records", "corridor", "confrontation", "exit"]


def test_every_slot_yields_a_real_scene_for_any_state():
    # The session loop walks ``world.slots`` directly and trusts ``pick`` to be
    # total — there is no end-of-spine ``None`` sentinel to guard against. Pin
    # that contract: every slot returns a real Scene (never None) and a non-empty
    # branch key under any player state, so the loop can never hand None to the
    # core step.
    states = (
        PlayerState(),
        _state_with("kindness", "kindness"),
        _state_with("control", "control"),
        _state_with("defiance", "defiance"),
        _state_with("kindness", "control"),  # a top tie -> default framing
    )
    for state in states:
        for slot in DEFAULT_WORLD.slots:
            scene, key = slot.pick(state)
            assert isinstance(scene, Scene)
            assert key


def test_tendency_priority_covers_all_tendencies():
    assert set(TENDENCY_PRIORITY) == set(TENDENCIES)
