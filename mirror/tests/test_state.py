"""Tests for the runtime mirror state and the per-choice update mechanics.

These guard the *behavioral* contract that makes the schema anti-mush at runtime:
a fresh state knows nothing, a choice moves only the axes it names, updates are
bounded, distributions stay normalized, state relaxes while traits persist, and
confidence only grows with evidence.
"""

from __future__ import annotations

import json

import pytest

from mirror.schema import MIRROR_SCHEMA, AttributeKind
from mirror.state import Choice, MirrorState, Signal


def test_fresh_state_knows_nothing():
    state = MirrorState.new()
    assert set(state.readings) == set(MIRROR_SCHEMA)
    for name, reading in state.readings.items():
        assert reading.confidence == 0.0, name
        assert reading.evidence_count == 0.0, name
    assert state.known() == {}  # nothing is confidently known yet


def test_neutral_starting_values_match_schema():
    state = MirrorState.new()
    assert state.readings["authority_trust"].value == 0.0  # bipolar rests at 0
    assert state.readings["curiosity"].value == 0.5  # unit neutral
    assert state.readings["frustration"].value == 0.0  # state rests calm
    mix = state.readings["playstyle_mix"].value
    assert sum(mix) == pytest.approx(1.0)


# --- the core anti-mush behavior: choices touch only what they signal ---------


def test_choice_moves_only_signaled_axes():
    state = MirrorState.new()
    before = {n: r.value for n, r in state.readings.items()}
    state.apply_choice(
        Choice("defy", signals=(Signal.toward("authority_trust", -1.0),))
    )
    # The signaled axis moved...
    assert state.readings["authority_trust"].value < 0.0
    # ...and every other axis is byte-for-byte unchanged. No global drift.
    for name, reading in state.readings.items():
        if name != "authority_trust":
            assert reading.value == before[name], name
            assert reading.confidence == 0.0, name


def test_signaled_axis_gains_confidence_others_stay_unknown():
    state = MirrorState.new()
    state.apply_choice(Choice("curious", signals=(Signal.toward("curiosity", 1.0),)))
    assert state.readings["curiosity"].confidence > 0.0
    assert state.readings["risk_tolerance"].confidence == 0.0


def test_inert_choice_changes_nothing():
    state = MirrorState.new()
    snap = state.snapshot()
    deltas = state.apply_choice(Choice("just_narrative", signals=()))
    assert deltas == {}
    assert state.snapshot() == snap


def test_apply_choice_returns_deltas_like_event_log():
    state = MirrorState.new()
    deltas = state.apply_choice(
        Choice(
            "tense_exit_probe",
            signals=(
                Signal.toward("authority_trust", -1.0),
                Signal.toward("boundary_testing", 1.0),
            ),
        )
    )
    assert set(deltas) == {"authority_trust", "boundary_testing"}
    assert deltas["authority_trust"] < 0  # moved toward defiant pole
    assert deltas["boundary_testing"] > 0


# --- updates are bounded and converge -----------------------------------------


def test_repeated_consistent_evidence_converges_toward_pole_without_overshoot():
    state = MirrorState.new()
    choice = Choice("comply", signals=(Signal.toward("authority_trust", 1.0),))
    last = -2.0
    for _ in range(50):
        state.apply_choice(choice)
        v = state.readings["authority_trust"].value
        assert -1.0 <= v <= 1.0  # never leaves range
        assert v >= last  # monotone toward the pole
        last = v
    assert state.readings["authority_trust"].value == pytest.approx(1.0, abs=1e-3)
    assert state.readings["authority_trust"].confidence > 0.9


def test_single_choice_cannot_slam_an_axis_to_the_extreme():
    state = MirrorState.new()
    state.apply_choice(Choice("x", signals=(Signal.toward("risk_tolerance", 1.0),)))
    # One full-weight step is learning_rate of the way there, not all the way.
    lr = MIRROR_SCHEMA["risk_tolerance"].learning_rate
    assert state.readings["risk_tolerance"].value == pytest.approx(lr)


def test_weight_scales_the_step():
    strong = MirrorState.new()
    weak = MirrorState.new()
    strong.apply_choice(Choice("s", signals=(Signal.toward("curiosity", 1.0, 1.0),)))
    weak.apply_choice(Choice("w", signals=(Signal.toward("curiosity", 1.0, 0.25),)))
    assert (
        strong.readings["curiosity"].value - 0.5
        > weak.readings["curiosity"].value - 0.5
    )


# --- distribution stays a distribution ----------------------------------------


def test_distribution_stays_normalized_and_concentrates_on_spent_mode():
    state = MirrorState.new()
    for _ in range(10):
        state.apply_choice(
            Choice("fight", signals=(Signal.spend("playstyle_mix", "combat"),))
        )
        mix = state.readings["playstyle_mix"].value
        assert sum(mix) == pytest.approx(1.0)  # always a valid distribution
        assert all(0.0 <= p <= 1.0 for p in mix)
    spec = MIRROR_SCHEMA["playstyle_mix"]
    combat_idx = spec.modes.index("combat")
    mix = state.readings["playstyle_mix"].value
    assert mix[combat_idx] == max(mix)  # combat now dominates the budget


def test_distribution_delta_is_change_in_spent_mode():
    state = MirrorState.new()
    deltas = state.apply_choice(
        Choice("talk", signals=(Signal.spend("playstyle_mix", "conversation"),))
    )
    assert deltas["playstyle_mix"] > 0  # conversation share rose


# --- state vs trait dynamics ---------------------------------------------------


def test_state_relaxes_on_tick_but_traits_persist():
    state = MirrorState.new()
    state.apply_choice(Choice("rage", signals=(Signal.toward("frustration", 1.0),)))
    state.apply_choice(Choice("defy", signals=(Signal.toward("authority_trust", -1.0),)))
    frustration_before = state.readings["frustration"].value
    trait_before = state.readings["authority_trust"].value

    state.tick()

    assert state.readings["frustration"].value < frustration_before  # relaxed
    assert state.readings["authority_trust"].value == trait_before  # trait persists


def test_frustration_decays_toward_calm_over_many_ticks():
    state = MirrorState.new()
    state.apply_choice(Choice("rage", signals=(Signal.toward("frustration", 1.0),)))
    for _ in range(50):
        state.tick()
    assert state.readings["frustration"].value == pytest.approx(0.0, abs=1e-3)


# --- guards against malformed signals (mush entry points) ---------------------


def test_unknown_attribute_signal_is_rejected():
    state = MirrorState.new()
    with pytest.raises(KeyError):
        state.apply_choice(Choice("x", signals=(Signal.toward("vibes", 1.0),)))


def test_out_of_range_target_is_rejected():
    state = MirrorState.new()
    with pytest.raises(ValueError):
        state.apply_choice(Choice("x", signals=(Signal.toward("curiosity", 2.0),)))


def test_bad_weight_is_rejected():
    state = MirrorState.new()
    with pytest.raises(ValueError):
        state.apply_choice(Choice("x", signals=(Signal("curiosity", target=1.0, weight=0.0),)))


def test_unknown_mode_is_rejected():
    state = MirrorState.new()
    with pytest.raises(ValueError):
        state.apply_choice(Choice("x", signals=(Signal.spend("playstyle_mix", "dancing"),)))


def test_scalar_signal_needs_target_distribution_needs_mode():
    state = MirrorState.new()
    with pytest.raises(ValueError):
        state.apply_choice(Choice("x", signals=(Signal.spend("curiosity", "combat"),)))
    with pytest.raises(ValueError):
        state.apply_choice(Choice("x", signals=(Signal.toward("playstyle_mix", 1.0),)))


# --- introspection / serialization --------------------------------------------


def test_known_filters_by_confidence():
    state = MirrorState.new()
    strong = Choice("c", signals=(Signal.toward("curiosity", 1.0),))
    for _ in range(8):  # push curiosity confidence above 0.5
        state.apply_choice(strong)
    known = state.known()
    assert "curiosity" in known
    assert "risk_tolerance" not in known  # never observed


def test_snapshot_is_json_serializable_and_round_trips():
    state = MirrorState.new()
    state.apply_choice(Choice("c", signals=(Signal.toward("curiosity", 1.0),)))
    state.apply_choice(Choice("f", signals=(Signal.spend("playstyle_mix", "combat"),)))
    snap = state.snapshot()
    text = json.dumps(snap)  # must not raise
    restored = json.loads(text)
    assert set(restored) == set(MIRROR_SCHEMA)
    assert isinstance(restored["playstyle_mix"]["value"], list)
    assert restored["curiosity"]["confidence"] > 0


# --- an integration sketch: a session yields a differentiated (non-mush) profile


def test_a_short_session_produces_a_differentiated_profile():
    """A defiant, cautious, system-probing player should read as exactly that —
    distinct axes pointing different directions, not one undifferentiated blob."""
    state = MirrorState.new()
    session = [
        Choice("question", signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "conversation"),
        )),
        Choice("inspect_exit", signals=(
            Signal.toward("boundary_testing", 1.0),
            Signal.spend("playstyle_mix", "exploration"),
        )),
        Choice("refuse_risky_offer", signals=(Signal.toward("risk_tolerance", -1.0),)),
        Choice("challenge", signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "conversation"),
        )),
        Choice("probe_again", signals=(Signal.toward("boundary_testing", 1.0),)),
        Choice("decline_again", signals=(Signal.toward("risk_tolerance", -1.0),)),
    ]
    for choice in session:
        state.apply_choice(choice)
        state.tick()

    assert state.readings["authority_trust"].value < -0.2  # defiant
    assert state.readings["risk_tolerance"].value < -0.1  # cautious
    assert state.readings["boundary_testing"].value > 0.55  # probing the system
    mix = state.readings["playstyle_mix"].value
    spec = MIRROR_SCHEMA["playstyle_mix"]
    assert mix[spec.modes.index("combat")] == min(mix)  # never fought

    # The axes carry genuinely different values — the profile is not mush.
    scalar_values = [
        state.readings[n].value
        for n, s in MIRROR_SCHEMA.items()
        if s.kind is not AttributeKind.DISTRIBUTION
    ]
    assert max(scalar_values) - min(scalar_values) > 0.5
