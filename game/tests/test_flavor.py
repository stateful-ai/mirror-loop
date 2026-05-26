"""Tests for the M1 adaptation beat's templated flavor pack.

These pin the three contracts the module ships:

1. The pack offers ≥3 distinct re-flavorings, each selectable by an
   :class:`~game.flavor.AdaptationDirective`.
2. Directive selection is a pure function of ``(seed, MirrorState)``.
3. The BASELINE / null path returns the canonical (scene-authored) prompt
   byte-for-byte — so a baseline run is UX-identical to "adaptation off"
   at the prompt layer.

The canonical text is also pinned against the actual ``.scene`` file so
the pack cannot silently drift from what the scene loader produces at
runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from game.flavor import (
    M1_ADAPTATION_BEAT_SLOT,
    M1_BEAT2_FLAVOR_PACK,
    AdaptationDirective,
    FlavorPack,
    select_directive,
)
from game.scenes import load_scene
from mirror.state import Choice, MirrorState, Signal


# --- Helpers -----------------------------------------------------------------


def _state_with(signals: dict[str, float], applications: int = 4) -> MirrorState:
    """Build a MirrorState by applying ``signals`` ``applications`` times.

    Four full-weight applications take both ``risk_tolerance`` (BIPOLAR,
    halflife 3) and ``boundary_testing`` (UNIT, halflife 3) past the
    confidence floor (0.5) and far enough from neutral to clear the lean
    floor (0.2) — see ``select_directive`` for the rule.
    """
    state = MirrorState.new()
    bundle = Choice(
        id="synthetic",
        signals=tuple(Signal.toward(attr, target) for attr, target in signals.items()),
    )
    for _ in range(applications):
        state.apply_choice(bundle)
    return state


# --- FlavorPack invariants ---------------------------------------------------


def test_pack_offers_three_distinct_re_flavorings():
    pack = M1_BEAT2_FLAVOR_PACK
    bodies = list(pack.variants.values())
    # ≥3 distinct re-flavorings is the locked acceptance bar.
    assert len(bodies) >= 3
    # Each non-canonical body is distinct from the canonical and from every
    # other variant — "distinct" in the acceptance criteria is taken at the
    # byte level, not the spirit.
    assert all(body != pack.canonical for body in bodies)
    assert len(set(bodies)) == len(bodies)


def test_pack_authored_for_every_non_baseline_directive():
    # The directive enum is the public switch; every non-baseline value
    # must have an authored body so the renderer's lookup is total.
    for directive in AdaptationDirective:
        if directive is AdaptationDirective.BASELINE:
            continue
        assert directive in M1_BEAT2_FLAVOR_PACK.variants


def test_pack_targets_the_m1_adaptation_beat():
    assert M1_BEAT2_FLAVOR_PACK.slot_key == M1_ADAPTATION_BEAT_SLOT
    assert M1_ADAPTATION_BEAT_SLOT == "act1_02_questionnaire_genre"


def test_canonical_matches_scene_file():
    """The pack's canonical prompt must equal the scene file's authored prompt.

    If the .scene authoring is revised and this test fails, update
    ``_BEAT2_CANONICAL`` in :mod:`game.flavor` to match — the two are
    one source of truth for the BASELINE path.
    """
    scene_path = (
        Path(__file__).resolve().parent.parent
        / "scenes"
        / "data"
        / "act1"
        / f"{M1_ADAPTATION_BEAT_SLOT}.scene"
    )
    scene = load_scene(scene_path)
    assert M1_BEAT2_FLAVOR_PACK.canonical == scene.prompt


# --- FlavorPack construction-time guards -------------------------------------


def test_pack_rejects_a_baseline_authored_variant():
    # Authoring a BASELINE body would silently override the null path's
    # canonical guarantee. Constructor must refuse.
    with pytest.raises(ValueError, match="BASELINE"):
        FlavorPack(
            slot_key="x",
            canonical="canon",
            variants={
                AdaptationDirective.BASELINE: "wrong",
                AdaptationDirective.CAUTIOUS: "c",
                AdaptationDirective.RECKLESS: "r",
                AdaptationDirective.PROBING: "p",
            },
        )


def test_pack_rejects_missing_non_baseline_variant():
    with pytest.raises(ValueError, match="missing re-flavorings"):
        FlavorPack(
            slot_key="x",
            canonical="canon",
            variants={
                AdaptationDirective.CAUTIOUS: "c",
                AdaptationDirective.RECKLESS: "r",
                # PROBING missing
            },
        )


def test_pack_rejects_variant_equal_to_canonical():
    with pytest.raises(ValueError, match="identical to the canonical"):
        FlavorPack(
            slot_key="x",
            canonical="canon",
            variants={
                AdaptationDirective.CAUTIOUS: "canon",
                AdaptationDirective.RECKLESS: "r",
                AdaptationDirective.PROBING: "p",
            },
        )


def test_pack_rejects_duplicate_variants():
    with pytest.raises(ValueError, match="duplicates"):
        FlavorPack(
            slot_key="x",
            canonical="canon",
            variants={
                AdaptationDirective.CAUTIOUS: "same body",
                AdaptationDirective.RECKLESS: "same body",
                AdaptationDirective.PROBING: "p",
            },
        )


def test_pack_rejects_empty_variant():
    with pytest.raises(ValueError, match="must be non-empty"):
        FlavorPack(
            slot_key="x",
            canonical="canon",
            variants={
                AdaptationDirective.CAUTIOUS: "   ",
                AdaptationDirective.RECKLESS: "r",
                AdaptationDirective.PROBING: "p",
            },
        )


# --- render(): each variant pinned + BASELINE -> canonical -------------------


def test_baseline_renders_canonical_text():
    pack = M1_BEAT2_FLAVOR_PACK
    assert pack.render(AdaptationDirective.BASELINE) == pack.canonical


def test_cautious_variant_is_pinned():
    pack = M1_BEAT2_FLAVOR_PACK
    body = pack.render(AdaptationDirective.CAUTIOUS)
    # Pin the authored shape: a slower, looked-after framing — buttons
    # *settle*, the prompt is preceded by "Before we begin".
    assert "Before we begin" in body
    assert "settle gently" in body
    assert "waiting for you to be ready" in body
    assert body != pack.canonical


def test_reckless_variant_is_pinned():
    pack = M1_BEAT2_FLAVOR_PACK
    body = pack.render(AdaptationDirective.RECKLESS)
    # Pin the authored shape: stakes-forward — snap, pick fast, daring.
    assert "snaps awake" in body
    assert "Pick fast" in body
    assert "daring you to commit" in body
    assert body != pack.canonical


def test_probing_variant_is_pinned():
    pack = M1_BEAT2_FLAVOR_PACK
    body = pack.render(AdaptationDirective.PROBING)
    # Pin the authored shape: a fourth, unlit shape the canonical does
    # not mention — the lab as something to be probed.
    assert "watching" in body
    assert "fourth shape" in body
    assert "bezel" in body
    assert body != pack.canonical


# --- select_directive: null/baseline -----------------------------------------


def test_a_fresh_mirror_state_selects_baseline():
    # No evidence anywhere => the Mirror has no read => BASELINE.
    state = MirrorState.new()
    assert select_directive(state, seed=42) is AdaptationDirective.BASELINE


def test_low_confidence_axis_selects_baseline():
    # One nudge isn't enough confidence: the axis is below the floor and
    # the directive must stay at BASELINE.
    state = MirrorState.new()
    state.apply_choice(
        Choice(id="weak", signals=(Signal.toward("risk_tolerance", -1.0),))
    )
    assert state.readings["risk_tolerance"].confidence < 0.5
    assert select_directive(state, seed=42) is AdaptationDirective.BASELINE


def test_confident_but_near_neutral_axis_selects_baseline():
    # Confidence cleared, but the value sits inside the lean floor -- the
    # 'no lean, no tailoring' rule (docs/ADAPTATION.md §4).
    state = MirrorState.new()
    # Repeatedly nudging toward a near-neutral target accumulates evidence
    # without driving the value far from zero.
    for _ in range(4):
        state.apply_choice(
            Choice(id="weak", signals=(Signal.toward("risk_tolerance", 0.05),))
        )
    assert state.readings["risk_tolerance"].confidence >= 0.5
    assert abs(float(state.readings["risk_tolerance"].value)) < 0.2
    assert select_directive(state, seed=42) is AdaptationDirective.BASELINE


# --- select_directive: per-directive selection -------------------------------


def test_confident_cautious_lean_selects_cautious():
    state = _state_with({"risk_tolerance": -1.0})
    assert select_directive(state, seed=42) is AdaptationDirective.CAUTIOUS


def test_confident_reckless_lean_selects_reckless():
    state = _state_with({"risk_tolerance": 1.0})
    assert select_directive(state, seed=42) is AdaptationDirective.RECKLESS


def test_confident_probing_lean_selects_probing():
    state = _state_with({"boundary_testing": 1.0})
    assert select_directive(state, seed=42) is AdaptationDirective.PROBING


# --- select_directive: determinism -------------------------------------------


def test_selection_is_deterministic_given_seed_and_state():
    state = _state_with({"risk_tolerance": -1.0})
    first = select_directive(state, seed=42)
    # Same inputs, same output — every time, irrespective of any hidden
    # global state.
    for _ in range(8):
        assert select_directive(state, seed=42) is first


def test_selection_is_deterministic_across_independent_states():
    # Two independently-built states with the same trajectory must read
    # identically. (MirrorState construction is the only impure step in
    # the pipeline; the directive is a pure function of the result.)
    a = _state_with({"risk_tolerance": 1.0})
    b = _state_with({"risk_tolerance": 1.0})
    assert select_directive(a, seed=7) == select_directive(b, seed=7)


def test_tied_leans_resolve_deterministically_by_seed():
    """When two axes lean equally hard, the seed breaks the tie deterministically.

    Applying ``risk_tolerance = -1.0`` and ``boundary_testing = 1.0``
    together for the same number of steps gives both axes the same
    confidence and the same normalised lean magnitude, so the scores are
    equal and the seed is the only thing that can decide.
    """
    state = _state_with({"risk_tolerance": -1.0, "boundary_testing": 1.0})
    # The selection still resolves to *one* directive, repeatably.
    pick_a = select_directive(state, seed=0)
    for _ in range(8):
        assert select_directive(state, seed=0) is pick_a

    pick_b = select_directive(state, seed=1)
    for _ in range(8):
        assert select_directive(state, seed=1) is pick_b

    # Both winning directives must be among the leaning candidates — the
    # selector never invents one out of thin air.
    candidates = {AdaptationDirective.CAUTIOUS, AdaptationDirective.PROBING}
    assert pick_a in candidates
    assert pick_b in candidates


# --- End-to-end: directive -> rendered body ----------------------------------


def test_each_directive_renders_a_distinct_body():
    """The whole point: every directive maps to a visibly different prompt.

    Pinned at the (directive -> body) level so the layer's user-facing
    surface — "what prose does the player see for this lean" — cannot
    rot without a test failure.
    """
    pack = M1_BEAT2_FLAVOR_PACK
    bodies = {d: pack.render(d) for d in AdaptationDirective}
    assert len(set(bodies.values())) == len(bodies)
    # The BASELINE body is the scene-authored canonical, by contract.
    assert bodies[AdaptationDirective.BASELINE] == pack.canonical
