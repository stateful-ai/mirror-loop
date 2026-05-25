"""Tests for the templated adaptation layer (``game.adapt``).

These pin the task's acceptance criteria directly:

* ``adapt(world, mirror)`` uses templates only (no LLM) — it is pure and
  deterministic, selecting/re-ordering hand-authored content,
* two contrasting play styles produce divergent output, and
* every adaptation logs its trigger (the Mirror snapshot it was a function of)
  and always passes the invariant check (reorder-only / agency-preserving).
"""

from __future__ import annotations

import pytest

from loop.core import Mirror, PlayerState, Scene

from game.adapt import AdaptedWorld, adapt, adapt_slot
from game.adaptation import AdaptationKind, AdaptationLog
from game.world import DEFAULT_WORLD, INTAKE, dominant_tendency
from guardrails.invariants import GuardrailViolation, validate_adaptation

# Real Choice objects, one per tendency, lifted from the world's intake scene, so
# a synthetic player state leans via genuine authored content.
_BY_TENDENCY = {c.tendency: c for c in INTAKE.choices}


def _lean(*tendencies: str) -> PlayerState:
    """A player state whose history leans the given tendencies (via real scenes)."""
    state = PlayerState()
    for i, tendency in enumerate(tendencies):
        choice = _BY_TENDENCY[tendency]
        scene = Scene(id=f"s{i}", prompt="", choices=(choice,))
        state = state.record(scene, choice)
    return state


# --- AC: "adapt(world, mirror) uses templates only (no LLM)" --------------------


def test_adapt_is_pure_and_deterministic():
    # No model, no randomness, no network: the same (world, mirror) yields a
    # byte-identical log every time — the structural stand-in for "no LLM".
    mirror = _lean("kindness", "kindness", "kindness")
    first = adapt(DEFAULT_WORLD, mirror)
    second = adapt(DEFAULT_WORLD, mirror)
    assert first == second
    assert first.log.to_json() == second.log.to_json()


def test_adapt_only_selects_authored_framings_and_reorders():
    # Every offered scene is one of the slot's authored scenes (selected, not
    # generated), presented with its choice set intact (re-ordered, not rewritten).
    mirror = _lean("control", "control", "control")
    world = adapt(DEFAULT_WORLD, mirror)
    for slot, adapted in zip(DEFAULT_WORLD.slots, world.slots):
        authored = (
            (slot.fixed,) if slot.fixed is not None else tuple(slot.variants.values())
        )
        assert adapted.declared in authored
        assert {c.id for c in adapted.offered.choices} == {
            c.id for c in adapted.declared.choices
        }


# --- AC: "two contrasting play styles produce divergent output" ----------------


def test_two_contrasting_play_styles_diverge():
    kind = adapt(DEFAULT_WORLD, _lean("kindness", "kindness", "kindness"))
    control = adapt(DEFAULT_WORLD, _lean("control", "control", "control"))

    kind_prompts = [s.offered.prompt for s in kind.slots]
    control_prompts = [s.offered.prompt for s in control.slots]
    kind_orders = [[c.id for c in s.offered.choices] for s in kind.slots]
    control_orders = [[c.id for c in s.offered.choices] for s in control.slots]

    # Materially different rooms, materially different orderings, and a different
    # audit log — the adaptation visibly bends to who is playing.
    assert kind_prompts != control_prompts
    assert kind_orders != control_orders
    assert kind.log != control.log
    assert kind.log.to_json() != control.log.to_json()


def test_divergence_follows_the_dominant_tendency():
    # The contrast is not incidental: each branch slot reveals the framing for that
    # player's lean, and the leading choice is theirs.
    for tendency in ("kindness", "control", "defiance"):
        world = adapt(DEFAULT_WORLD, _lean(tendency, tendency, tendency))
        for adapted in world.slots:
            if adapted.reframed:
                assert adapted.branch_key == tendency
            chosen_lead = adapted.offered.choices[0].tendency
            # Once a lean exists, the player's tendency is surfaced first wherever
            # the scene offers it.
            assert chosen_lead == tendency


# --- AC: "every adaptation logs its trigger" -----------------------------------


def test_every_adaptation_records_its_trigger_snapshot():
    mirror = _lean("defiance", "defiance", "defiance")
    world = adapt(DEFAULT_WORLD, mirror)
    log = world.log
    assert log.adaptations, "a consistent player must produce at least one adaptation"
    for adaptation in log.adaptations:
        prov = adaptation.provenance
        # The trigger snapshot is the exact read the decision was a function of.
        assert prov.trigger_snapshot.dominant == dominant_tendency(mirror) == "defiance"
        assert prov.trigger_snapshot.turn_count == mirror.turn_count
        assert prov.source_event_seq == mirror.turn_count


def test_both_surfaces_are_logged_with_their_kind():
    # A leaning player triggers both surfaces: a branch reveal and a re-ordering,
    # each recorded under its own kind.
    world = adapt(DEFAULT_WORLD, _lean("control", "control", "control"))
    kinds = {a.kind for a in world.log.adaptations}
    assert AdaptationKind.BRANCH_SELECTION in kinds
    assert AdaptationKind.CHOICE_REORDERING in kinds

    # The branch reveal at records names the revealed framing; the re-ordering at
    # confrontation names the predicted-first ordering.
    records = world.slot("records")
    branch = next(a for a in records.adaptations if a.kind is AdaptationKind.BRANCH_SELECTION)
    assert branch.revealed == "control"
    confront = world.slot("confrontation")
    reorder = next(a for a in confront.adaptations if a.kind is AdaptationKind.CHOICE_REORDERING)
    assert reorder.predicted_choice == "c_log"  # control option, declared 2nd, lifted first


def test_log_round_trips_through_json():
    world = adapt(DEFAULT_WORLD, _lean("kindness", "kindness", "kindness"))
    restored = AdaptationLog.from_json(world.log.to_json())
    assert restored == world.log


def test_log_is_only_actual_adaptations():
    # The neutral, no-lean presentation records nothing: a slot left in its
    # declared order under the default framing is the identity, not an adaptation.
    world = adapt(DEFAULT_WORLD, _lean("kindness", "kindness", "kindness"))
    intake = world.slot("intake")
    # Intake declares kindness first, so a kind player triggers no re-ordering and
    # it is a fixed slot (no branch reveal) — hence no logged adaptation.
    assert not intake.reordered
    assert intake.adaptations == ()


# --- AC: "always passes the invariant check" -----------------------------------


def test_every_presentation_passes_the_reorder_only_invariant():
    # Across every lean (and no lean), every offered scene is a reorder-only,
    # agency-preserving presentation of the framing the layer selected.
    states = [
        PlayerState(),
        _lean("kindness"),
        _lean("kindness", "control"),  # a tie: no lean
        _lean("kindness", "kindness", "kindness"),
        _lean("control", "control", "control"),
        _lean("defiance", "defiance", "defiance"),
    ]
    for state in states:
        world = adapt(DEFAULT_WORLD, state)
        for adapted in world.slots:
            assert validate_adaptation(adapted.declared, adapted.offered).ok
            # Agency preserved: the room still offers all three tendencies.
            assert {c.tendency for c in adapted.offered.choices} == {
                "kindness",
                "control",
                "defiance",
            }


def test_layer_raises_if_the_engine_breaks_reorder_only():
    # The invariant check is live, not decorative: an engine that rewrites a scene
    # (here, dropping a choice) is caught and refused rather than shipped.
    class _DroppingMirror(Mirror):
        def adapt(self, state, scene):
            return scene.__class__(
                id=scene.id, prompt=scene.prompt, choices=scene.choices[:-1]
            )

    with pytest.raises(GuardrailViolation):
        adapt(DEFAULT_WORLD, _lean("kindness", "kindness", "kindness"), engine=_DroppingMirror())


# --- The toggle: one layer, on or off ------------------------------------------


def test_disabled_layer_is_the_identity_with_an_empty_log():
    mirror = _lean("defiance", "defiance", "defiance")
    off = adapt(DEFAULT_WORLD, mirror, enabled=False)

    # Neutral framing, declared order everywhere, and nothing logged.
    assert off.log == AdaptationLog()
    for slot, adapted in zip(DEFAULT_WORLD.slots, off.slots):
        assert not adapted.reordered
        assert not adapted.reframed
        assert adapted.branch_key in ("fixed", "default")


def test_disabled_layer_is_invariant_to_how_the_player_plays():
    # With the layer off, two contrasting players are presented byte-identical
    # content — the defining property of the toggle's "off" state.
    kind = adapt(DEFAULT_WORLD, _lean("kindness", "kindness", "kindness"), enabled=False)
    defiant = adapt(DEFAULT_WORLD, _lean("defiance", "defiance", "defiance"), enabled=False)
    assert [s.offered for s in kind.slots] == [s.offered for s in defiant.slots]


def test_toggle_changes_the_output_for_the_same_player():
    mirror = _lean("control", "control", "control")
    on = adapt(DEFAULT_WORLD, mirror, enabled=True)
    off = adapt(DEFAULT_WORLD, mirror, enabled=False)
    on_prompts = [s.offered.prompt for s in on.slots]
    off_prompts = [s.offered.prompt for s in off.slots]
    assert on_prompts != off_prompts
    assert on.log.adaptations and not off.log.adaptations


# --- No-lean and per-slot behavior ---------------------------------------------


def test_no_lean_is_the_identity_even_when_enabled():
    # An empty model has no dominant tendency, so the enabled layer makes no
    # decision: neutral framing, declared order, empty log.
    world = adapt(DEFAULT_WORLD, PlayerState())
    assert world.log == AdaptationLog()
    for adapted in world.slots:
        assert not adapted.reordered
        assert adapted.branch_key in ("fixed", "default")


def test_top_tie_suppresses_branch_selection():
    # The two surfaces resolve "no clear leader" differently (docs/ADAPTATION.md §2):
    # across-scene selection takes the strict argmax, so an exact top tie is *not* a
    # lean and no framing is revealed. (In-scene re-ordering still ranks by the tally,
    # so it may reorder — that is the documented asymmetry, not a guess.)
    state = _lean("kindness", "control")
    assert dominant_tendency(state) is None
    world = adapt(DEFAULT_WORLD, state)
    assert all(not s.reframed for s in world.slots)
    assert not any(
        a.kind is AdaptationKind.BRANCH_SELECTION for a in world.log.adaptations
    )


def test_adapt_slot_matches_the_whole_world_walk():
    # adapt() is exactly adapt_slot() mapped over the spine under one frozen read.
    mirror = _lean("kindness", "kindness", "kindness")
    engine = Mirror()
    world = adapt(DEFAULT_WORLD, mirror, engine=engine)
    for slot, adapted in zip(DEFAULT_WORLD.slots, world.slots):
        assert adapt_slot(slot, mirror, engine=engine) == adapted


def test_adapted_world_slot_lookup():
    world = adapt(DEFAULT_WORLD, _lean("kindness", "kindness", "kindness"))
    assert isinstance(world, AdaptedWorld)
    assert world.slot("exit").slot_key == "exit"
    with pytest.raises(KeyError):
        world.slot("nope")
