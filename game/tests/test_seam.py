"""The single shared adaptation seam — ``baseline == adaptive minus the layer``.

The architecture principle this pins: *baseline and adaptive share one adaptation
seam where baseline is the identity transform, so parity is structural rather than
tested-in after the fact — never a forked code path.* The seam
(:class:`~game.variants.Variant`) is one pipeline; the adaptation is an injected
:class:`~game.variants.AdaptationLayer`. An arm is the seam plus a layer, so two
arms can differ in nothing but the layer.

The task's acceptance criteria, each made executable below:

* **both paths are identical except the injected adaptation** — every arm is the
  same :class:`Variant` type, the two seam operations have a *single*
  implementation (no per-arm override), and the adaptive and baseline arms are
  equal value-for-value once their cosmetic name is normalised and the layer is
  swapped.
* **with the no-op/off adaptation, output is byte-identical to baseline for the
  same (seed, inputs)** — ``ADAPTIVE.without_layer()`` (the seam with the layer
  removed) produces byte-identical output to the canonical :data:`FIXED` baseline
  across a seeded population and every persona, transcript and gate-log alike.

The byte-identity would be vacuous if the layer did nothing, so the last group
proves the layer is real: with it on, a leaning player sees materially different
content.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loop.core import Mirror, PlayerState, Scene

from game.playtest import build_population
from game.session import (
    PERSONAS,
    Session,
    persona_policy,
    play_session,
    transcript,
)
from game.variants import (
    ADAPTIVE,
    FIXED,
    NO_LAYER,
    TENDENCY_MIRRORING,
    Variant,
    random_variant,
)
from game.world import DEFAULT_WORLD


def _lean(tendency: str) -> PlayerState:
    """A state that leans ``tendency`` twice, via a real choice from the spine."""
    choice = next(
        c for c in DEFAULT_WORLD.slots[0].fixed.choices if c.tendency == tendency
    )
    scene = Scene(id="lean", prompt="", choices=(choice,))
    return PlayerState().record(scene, choice).record(scene, choice)


def _content(session: Session) -> tuple:
    """Everything a session *produces*, with the cosmetic arm label removed.

    The arm name is a self-labelling tag for analysis, not player-facing output,
    so it is dropped before comparison. Two sessions equal here are byte-identical
    in their transcript (the full player-facing stream), their gate-shaped log,
    their scored decision points, and their final player model.
    """
    log = session.session_log()
    log.pop("variant")
    return (
        transcript(session),
        json.dumps(log, sort_keys=True),
        tuple(session.decision_points()),
        session.final_state,
    )


# --- both paths are identical except the injected adaptation --------------------


@pytest.mark.parametrize("variant", [ADAPTIVE, FIXED, random_variant(0)])
def test_every_arm_is_the_same_seam_type(variant):
    # One pipeline class for every arm — there is no per-arm Variant subclass, so
    # the seam an arm runs cannot diverge by subtype.
    assert type(variant) is Variant


def test_seam_operations_have_a_single_implementation():
    # The two seam operations are defined once (on Variant) and never overridden
    # per arm, so the code each arm runs through the seam is the *same* code; the
    # only thing that can differ is the injected layer it delegates to.
    assert type(ADAPTIVE).select_scene is Variant.select_scene
    assert type(FIXED).select_scene is Variant.select_scene
    assert type(random_variant(0)).select_scene is Variant.select_scene
    assert type(ADAPTIVE).order_choices is Variant.order_choices
    assert type(FIXED).order_choices is Variant.order_choices


def test_adaptive_and_baseline_differ_only_in_the_injected_layer():
    # Same seam, different layer plugged in: swap adaptive's layer for the
    # baseline's (and normalise the cosmetic arm name) and you *are* the baseline.
    assert ADAPTIVE.layer is TENDENCY_MIRRORING
    assert FIXED.layer is NO_LAYER
    assert ADAPTIVE.layer is not FIXED.layer
    assert replace(ADAPTIVE, layer=FIXED.layer, name=FIXED.name) == FIXED


# --- baseline == adaptive minus the layer (structural) --------------------------


def test_without_layer_injects_the_identity_transform():
    off = ADAPTIVE.without_layer()
    # The layer removed is exactly the baseline's no-op layer (same singleton)...
    assert off.layer is NO_LAYER
    assert off.layer is FIXED.layer
    # ...so adaptive-minus-the-layer differs from the baseline only by arm label.
    assert replace(off, name=FIXED.name) == FIXED


def test_no_op_layer_is_a_genuine_identity_transform():
    # The off layer reveals the neutral framing and never re-orders, for every
    # slot under every lean — i.e. it is literally the identity, so the seam with
    # it injected adds nothing to the engine's raw content.
    mirror = Mirror()
    states = (
        PlayerState(),
        _lean("kindness"),
        _lean("control"),
        _lean("defiance"),
    )
    for state in states:
        for slot in DEFAULT_WORLD.slots:
            scene, key = NO_LAYER.select_scene(slot, state)
            assert key in ("fixed", "default")
            neutral = slot.fixed if slot.fixed is not None else slot.variants["default"]
            assert scene is neutral  # the neutral framing, not a tailored one
            # order_choices returns the very same scene object — no re-ordering.
            assert NO_LAYER.order_choices(mirror, state, scene) is scene


# --- with the no-op/off layer, output is byte-identical to baseline --------------


@pytest.mark.parametrize("persona", sorted(PERSONAS))
def test_no_op_output_is_byte_identical_to_baseline_per_persona(persona):
    # For the same inputs (a fixed persona's choices), the seam with its layer
    # removed yields byte-identical output to the canonical baseline.
    off = play_session(PERSONAS[persona](), variant=ADAPTIVE.without_layer())
    base = play_session(PERSONAS[persona](), variant=FIXED)
    assert _content(off) == _content(base)


def test_no_op_output_is_byte_identical_to_baseline_across_seeded_population():
    # Sweep a seeded population — a broad spread of (primary, lean) and so of
    # input sequences — and assert byte-identity for every one. This is the
    # "same (seed, inputs)" guarantee at population scale: removing the layer is
    # indistinguishable from the baseline, run for run.
    off = ADAPTIVE.without_layer()
    for player in build_population(n=15):
        a = play_session(player.policy(), variant=off)
        b = play_session(player.policy(), variant=FIXED)
        assert _content(a) == _content(b)


# --- the byte-identity is non-vacuous: the layer is real ------------------------


def test_the_layer_actually_changes_output():
    # If the real layer were itself a no-op, the byte-identity above would prove
    # nothing. A leaning player must see different content with the layer on vs
    # off — and the difference is the adaptation's two surfaces (re-ordering and
    # tailored framing), present only with the layer on.
    on = play_session(persona_policy("kindness"), variant=ADAPTIVE)
    off = play_session(persona_policy("kindness"), variant=ADAPTIVE.without_layer())
    assert transcript(on) != transcript(off)
    assert any(r.reordered for r in on.records)
    assert not any(r.reordered for r in off.records)
    assert any(r.branch_key not in ("fixed", "default") for r in on.records)
    assert all(r.branch_key in ("fixed", "default") for r in off.records)
