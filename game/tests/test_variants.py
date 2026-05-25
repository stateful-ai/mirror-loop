"""The non-adaptive baseline arms — the A/B feel-test toggle.

Acceptance: *same shell, fixed/random content, for A/B feel-testing.* Each clause
is pinned below against the one principle that keeps the comparison honest — the
baseline is the **same engine with the adaptation seam set to identity (or a
player-independent placebo), toggled by one flag, never a forked code path**:

* **same shell** — every variant plays the identical spine (same slots, same loop
  count, same scenes available) and keeps the Reflection/legibility beat, which
  is a render of observed behavior, not an adaptation. Only the *contingency* of
  content on the player differs.
* **fixed content** — the ``fixed`` arm is the identity transform: it never
  re-orders a scene and never tailors framing, so nothing the player does changes
  what they are offered.
* **random content** — the ``random`` arm is the placebo: content visibly varies
  but is *independent of the player* (two different players get identical
  framings and orderings) and is deterministically replayable from its seed.
* **toggleable / honest A/B** — the same player produces materially different
  content under ``adaptive`` vs. the baselines, and ``adaptive`` is the default so
  existing behavior is unchanged.
"""

from __future__ import annotations

import pytest

from acceptance.predictability import evaluate
from loop.core import PlayerState, Scene

from game.session import (
    MAX_LOOPS,
    MIN_LOOPS,
    erratic_policy,
    persona_policy,
    play_session,
    transcript,
)
from game.variants import (
    ADAPTIVE,
    FIXED,
    VARIANT_NAMES,
    Variant,
    build_variant,
    random_variant,
)
from game.world import DEFAULT_WORLD

ALL_VARIANTS: tuple[Variant, ...] = (ADAPTIVE, FIXED, random_variant(0))


def _lean(tendency: str) -> PlayerState:
    """A state that leans ``tendency`` twice, via a real choice from the spine."""
    state = PlayerState()
    choice = next(
        c for c in DEFAULT_WORLD.slots[0].fixed.choices if c.tendency == tendency
    )
    scene = Scene(id="lean", prompt="", choices=(choice,))
    return state.record(scene, choice).record(scene, choice)


def _prompts(session) -> list[str]:
    return [r.offered.prompt for r in session.records]


def _orders(session) -> list[list[str]]:
    return [[c.id for c in r.offered.choices] for r in session.records]


# --- "same shell": the spine and the legibility beat survive every arm ----------


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_every_variant_plays_the_same_spine(variant):
    session = play_session(persona_policy("kindness"), variant=variant)
    assert MIN_LOOPS <= session.loop_count <= MAX_LOOPS
    # Same slots, in the same order — the shell does not change between arms.
    assert [r.offered.id for r in session.records] == [
        "intake",
        "records",
        "corridor",
        "confrontation",
        "exit",
    ]


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_select_scene_is_total_for_every_variant(variant):
    # The session loop walks every slot and feeds the result straight to the core
    # step with no None-guard: the seam must be *total*. Pin that each variant
    # returns a real Scene and a non-empty branch key for every slot, under every
    # player lean — so the baseline arms can never crash where the old per-loop
    # ``None`` guard used to sit.
    states = (
        PlayerState(),
        _lean("kindness"),
        _lean("control"),
        _lean("defiance"),
    )
    for state in states:
        for slot in DEFAULT_WORLD.slots:
            scene, key = variant.select_scene(slot, state)
            assert scene is not None
            assert key


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_every_variant_runs_the_full_spine_length(variant):
    # Session length is the spine length in every arm — the baseline does not
    # shorten or lengthen the session, it only changes content contingency.
    session = play_session(persona_policy("defiance"), variant=variant)
    assert session.loop_count == DEFAULT_WORLD.length == 5


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_every_variant_keeps_the_reflection_beat(variant):
    # The legibility beat is a render of observed behavior, not an adaptation, so
    # a consistent player triggers it exactly once in every arm — without it the
    # A/B would have nothing to measure.
    session = play_session(persona_policy("kindness"), variant=variant)
    reflections = [r for r in session.records if r.result.reflection is not None]
    assert len(reflections) == 1
    assert reflections[0].result.reflection.tendency == "kindness"


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_every_variant_preserves_agency(variant):
    # Every arm still offers — and records — the player's chosen tendency; the
    # baseline reframes/​re-orders the room, it never removes a door.
    session = play_session(persona_policy("control"), variant=variant)
    for record in session.records:
        chosen = record.offered.choice(record.result.actual_action)
        assert chosen.tendency == "control"


# --- "fixed content": the identity transform ------------------------------------


def test_fixed_baseline_never_reorders_a_scene():
    # Even the confrontation scene (declared kindness-last) is left untouched: the
    # kind option that the adaptive arm surfaces to the top stays last.
    session = play_session(persona_policy("kindness"), variant=FIXED)
    assert all(not r.reordered for r in session.records)
    confront = next(r for r in session.records if r.offered.id == "confrontation")
    assert confront.offered.choices[-1].id == "c_wait"


def test_fixed_baseline_never_tailors_framing():
    # Branch slots always reveal the neutral "default" framing; fixed slots stay
    # "fixed". Nothing the player does selects a different room.
    session = play_session(persona_policy("kindness"), variant=FIXED)
    assert {r.branch_key for r in session.records} == {"fixed", "default"}


def test_fixed_baseline_is_invariant_to_how_the_player_plays():
    # The defining property of the control: different players see byte-identical
    # content (same prompts, same choice orders). Only their own choices differ.
    kind = play_session(persona_policy("kindness"), variant=FIXED)
    defiant = play_session(persona_policy("defiance"), variant=FIXED)
    assert _prompts(kind) == _prompts(defiant)
    assert _orders(kind) == _orders(defiant)


# --- "toggleable": the baseline genuinely differs from the adaptive arm ----------


def test_adaptive_and_fixed_offer_different_content_to_the_same_player():
    adaptive = play_session(persona_policy("kindness"), variant=ADAPTIVE)
    fixed = play_session(persona_policy("kindness"), variant=FIXED)
    # Same player, same shell — but the adaptive arm bends the rooms to them and
    # the baseline does not. If these matched, the toggle would be a no-op.
    assert _prompts(adaptive) != _prompts(fixed)
    assert any(r.reordered for r in adaptive.records)
    assert not any(r.reordered for r in fixed.records)


# --- "random content": a player-independent, deterministic placebo ---------------


def test_random_baseline_is_independent_of_the_player():
    # The placebo *looks* like it adapts, but the variation is not driven by the
    # player: two different players get identical framings and choice orders.
    variant = random_variant(7)
    kind = play_session(persona_policy("kindness"), variant=variant)
    defiant = play_session(persona_policy("defiance"), variant=variant)
    assert _prompts(kind) == _prompts(defiant)
    assert _orders(kind) == _orders(defiant)


def test_random_baseline_actually_varies_content():
    # ...and it is not merely the identity: it reveals non-neutral framings and/or
    # re-orders choices, so on the surface it is indistinguishable from adaptation.
    session = play_session(persona_policy("kindness"), variant=random_variant(7))
    tailored_framing = any(
        r.branch_key not in ("fixed", "default") for r in session.records
    )
    reordered = any(r.reordered for r in session.records)
    assert tailored_framing or reordered


def test_random_baseline_is_deterministic_and_replayable():
    # Same seed -> byte-identical session, every time and in any process (the seed
    # is hashed deterministically). A stateless variant instance can be reused.
    variant = random_variant(3)
    first = transcript(play_session(persona_policy("kindness"), variant=variant))
    second = transcript(play_session(persona_policy("kindness"), variant=variant))
    fresh = transcript(play_session(persona_policy("kindness"), variant=random_variant(3)))
    assert first == second == fresh


def test_random_baseline_seed_changes_the_content():
    # Different seeds give different (but each fixed) placebo content, so a
    # playtest can vary the decoy without it ever tracking the player.
    framings = {
        tuple(r.branch_key for r in play_session(persona_policy("kindness"), variant=random_variant(s)).records)
        for s in range(8)
    }
    assert len(framings) > 1


# --- Every arm still feeds the locked acceptance gate ---------------------------


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_every_variant_emits_a_gate_compatible_log(variant):
    session = play_session(persona_policy("kindness"), variant=variant)
    log = session.session_log()
    assert log["variant"] == variant.name
    assert len(log["decision_points"]) == session.loop_count
    assert evaluate(session.decision_points()).n == session.loop_count


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_erratic_player_never_locks_the_model_in_any_arm(variant):
    # The escape archetype holds across arms: cycling tendencies never confirms a
    # pattern, regardless of how content is presented.
    session = play_session(erratic_policy(), variant=variant)
    assert all(r.result.reflection is None for r in session.records)
    assert session.final_state.announced == frozenset()


# --- The single toggle: defaults and resolution ---------------------------------


def test_adaptive_is_the_default_arm():
    # Omitting the toggle must reproduce the real game exactly (back-compat).
    explicit = transcript(play_session(persona_policy("kindness"), variant=ADAPTIVE))
    default = transcript(play_session(persona_policy("kindness")))
    assert default == explicit
    assert play_session(persona_policy("kindness")).variant_name == "adaptive"


def test_build_variant_resolves_each_name():
    assert build_variant("adaptive") is ADAPTIVE
    assert build_variant("fixed") is FIXED
    assert build_variant("random", seed=5).name == "random"
    assert set(VARIANT_NAMES) == {"adaptive", "fixed", "random"}


def test_build_variant_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="unknown variant"):
        build_variant("placebo")


def test_build_random_variant_seed_is_honoured():
    a = play_session(persona_policy("kindness"), variant=build_variant("random", seed=1))
    b = play_session(persona_policy("kindness"), variant=build_variant("random", seed=2))
    assert _prompts(a) != _prompts(b) or _orders(a) != _orders(b)
