"""Tests for the static mirror schema and its anti-mush coherence invariants.

These guard the *design* contract: the schema must stay a small set of well-typed,
orthogonal, fully-provenanced axes. If a future edit reintroduces mush (an
unnamed pole, a trait that secretly decays, a seed feature silently dropped),
one of these fails.
"""

from __future__ import annotations

import re

import pytest

from mirror.schema import (
    MIRROR_SCHEMA,
    SEED_FEATURE_MAP,
    AttributeKind,
    Dynamics,
    assert_coherent,
    coherence_report,
    value_range,
)

# The fifteen features the seed design lists in game_design.md §6.1. Hard-coded
# here so the test fails loudly if the schema's provenance drifts from the seed.
SEED_6_1_FEATURES = {
    "combat_rate",
    "conversation_rate",
    "exploration_rate",
    "quest_following_rate",
    "moral_consistency",
    "risk_tolerance",
    "loot_behavior",
    "lore_engagement",
    "failure_recovery",
    "system_boundary_testing",
    "authority_trust",
    "agency_resistance",
    "curiosity_score",
    "frustration_risk",
    "prediction_confidence",
}


# --- coherence (the anti-mush review, executable) ------------------------------


def test_schema_is_coherent():
    report = coherence_report()
    assert report.ok, report.render()
    # assert_coherent already runs at import; calling again must not raise.
    assert_coherent()


def test_every_axis_names_both_ends():
    # An axis you can't label at both ends measures nothing in particular.
    for name, spec in MIRROR_SCHEMA.items():
        if spec.kind is AttributeKind.DISTRIBUTION:
            assert len(spec.modes) >= 2, name
            assert not spec.poles, name
        else:
            assert len(spec.poles) == 2 and all(p.strip() for p in spec.poles), name


def test_bipolar_axes_rest_at_zero():
    for name, spec in MIRROR_SCHEMA.items():
        if spec.kind is AttributeKind.BIPOLAR:
            assert spec.neutral == 0.0, name
            assert value_range(spec.kind) == (-1.0, 1.0)


def test_trait_state_timescale_split_is_explicit():
    # Traits never self-relax; states always do. This is the line between
    # "who they are" and "how they feel right now".
    for name, spec in MIRROR_SCHEMA.items():
        if spec.dynamics is Dynamics.TRAIT:
            assert spec.decay_per_turn == 0.0, name
        else:
            assert spec.decay_per_turn > 0.0, name


def test_learning_rates_and_halflives_are_sane():
    for name, spec in MIRROR_SCHEMA.items():
        assert 0.0 < spec.learning_rate <= 1.0, name
        assert 0.0 <= spec.decay_per_turn < 1.0, name
        assert spec.evidence_halflife > 0.0, name


def test_descriptions_are_present():
    for name, spec in MIRROR_SCHEMA.items():
        assert spec.description.strip(), name


# --- seed provenance: nothing dropped, nothing invented -----------------------


def test_seed_feature_map_covers_exactly_section_6_1():
    assert set(SEED_FEATURE_MAP) == SEED_6_1_FEATURES


def test_every_seed_feature_maps_to_a_real_axis_or_explicit_exclusion():
    for feature, target in SEED_FEATURE_MAP.items():
        if target.startswith("excluded:"):
            assert len(target.split(":", 1)[1]) > 0, feature  # has a reason
        else:
            assert target in MIRROR_SCHEMA, feature


def test_prediction_confidence_is_excluded_as_meta():
    # It's the model's confidence in its forecast, not a fact about the player.
    assert SEED_FEATURE_MAP["prediction_confidence"].startswith("excluded:")


def test_agency_resistance_folds_into_authority_trust():
    # The clearest mush in the seed: two near-redundant axes. They collapse to
    # one signed axis here.
    assert SEED_FEATURE_MAP["authority_trust"] == "authority_trust"
    assert SEED_FEATURE_MAP["agency_resistance"] == "authority_trust"


def test_playstyle_rates_collapse_into_one_distribution():
    for rate in ("combat_rate", "conversation_rate", "exploration_rate", "loot_behavior"):
        assert SEED_FEATURE_MAP[rate] == "playstyle_mix"
    assert MIRROR_SCHEMA["playstyle_mix"].kind is AttributeKind.DISTRIBUTION


def test_every_axis_has_provenance():
    mapped = {t for t in SEED_FEATURE_MAP.values() if not t.startswith("excluded:")}
    assert mapped == set(MIRROR_SCHEMA)


def test_schema_is_small_enough_to_stay_orthogonal():
    # A soft mush guard: the whole point was to shrink 15 loose features into a
    # handful of orthogonal axes. If this ever balloons, re-review.
    assert len(MIRROR_SCHEMA) <= 10


# --- spec helpers --------------------------------------------------------------


def test_neutral_value_for_distribution_is_uniform():
    spec = MIRROR_SCHEMA["playstyle_mix"]
    neutral = spec.neutral_value()
    assert isinstance(neutral, tuple)
    assert neutral == pytest.approx(tuple(1 / len(spec.modes) for _ in spec.modes))
    assert sum(neutral) == pytest.approx(1.0)


def test_confidence_is_zero_without_evidence_and_monotone():
    spec = MIRROR_SCHEMA["authority_trust"]
    assert spec.confidence(0) == 0.0
    seq = [spec.confidence(n) for n in range(0, 10)]
    assert all(b >= a for a, b in zip(seq, seq[1:]))  # non-decreasing
    assert spec.confidence(spec.evidence_halflife) == pytest.approx(0.5)
    assert seq[-1] < 1.0  # saturates toward, never reaches, 1


def test_clamp_keeps_scalars_in_range():
    bip = MIRROR_SCHEMA["authority_trust"]
    assert bip.clamp(5.0) == 1.0 and bip.clamp(-5.0) == -1.0
    unit = MIRROR_SCHEMA["curiosity"]
    assert unit.clamp(5.0) == 1.0 and unit.clamp(-5.0) == 0.0


def test_axis_names_are_snake_case():
    for name in MIRROR_SCHEMA:
        assert re.fullmatch(r"[a-z][a-z_]*", name), name
