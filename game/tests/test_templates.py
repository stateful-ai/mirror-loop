"""Templated adaptations — the Mirror's voice, filled by the player model only.

These pin the escalation ladder (Calibration → Observation → Prediction →
Confrontation) and the closing readout. The contract under test: every line is a
fixed authored template the *observed* model fills in, the stage is chosen by how
much the Mirror has learned (never the loop number), and the broken-prediction
case is surfaced — the escape mechanic's first visible appearance.
"""

from __future__ import annotations

from game.templates import (
    STAGE_TITLES,
    TENDENCY_FLAVOR,
    adapt_message,
    final_report,
)


def _msg(**overrides):
    base = dict(
        dominant="kindness",
        dominant_count=1,
        total=1,
        just_noticed=False,
        model_locked=False,
        predicted_hit=False,
        is_finale=False,
    )
    base.update(overrides)
    return adapt_message(**base)


# --- Stage selection: driven by what the Mirror has learned, not the loop # -----


def test_first_moment_is_calibration():
    msg = _msg(total=1, dominant_count=1)
    assert msg.stage == 1
    assert msg.title == "CALIBRATION"


def test_a_lean_without_a_confirmed_pattern_is_observation():
    msg = _msg(total=2, dominant_count=2)
    assert msg.stage == 2
    assert msg.title == "OBSERVATION"
    assert "2 of 2" in msg.body


def test_confirming_a_pattern_is_prediction():
    msg = _msg(total=3, dominant_count=3, just_noticed=True)
    assert msg.stage == 3
    assert msg.title == "PREDICTION"
    assert "Pattern confirmed: kindness" in msg.body


def test_a_locked_model_that_predicts_correctly_says_as_predicted():
    msg = _msg(total=4, dominant_count=4, model_locked=True, predicted_hit=True)
    assert msg.stage == 3
    assert "As predicted" in msg.body


def test_a_broken_prediction_is_surfaced_as_recalibration():
    # The escape mechanic's first visible appearance: the player slipped the model.
    msg = _msg(total=4, dominant_count=3, model_locked=True, predicted_hit=False)
    assert msg.stage == 3
    assert "Unanticipated" in msg.body
    assert "Recalibrating" in msg.body


def test_finale_with_a_locked_model_is_confrontation():
    msg = _msg(total=5, dominant_count=5, model_locked=True, is_finale=True)
    assert msg.stage == 4
    assert msg.title == "CONFRONTATION"
    assert "Predictability index: 100%" in msg.body


def test_finale_without_a_locked_model_does_not_confront():
    # An unreadable player never escalates to Confrontation, even on the last loop.
    msg = _msg(total=5, dominant_count=2, model_locked=False, is_finale=True)
    assert msg.stage != 4


def test_every_stage_title_is_defined():
    for stage in (1, 2, 3, 4):
        assert stage in STAGE_TITLES


def test_message_render_includes_title_and_body():
    msg = _msg(total=2, dominant_count=2)
    rendered = msg.render()
    assert msg.title in rendered
    assert msg.body in rendered
    assert rendered.startswith("MIRROR //")


# --- Per-tendency flavour: in-fiction observations of *play* -------------------


def test_flavor_exists_for_each_modeled_tendency():
    for tendency in ("kindness", "control", "defiance"):
        assert tendency in TENDENCY_FLAVOR


# --- Closing report: a diegetic render of the gate's top-1 accuracy ------------


def test_final_report_reads_high_confidence_for_a_predictable_player():
    report = final_report(hits=5, total=5, accuracy=1.0, dominant="kindness")
    assert "PREDICTABILITY INDEX : 100%" in report
    assert "MODEL CONFIDENCE     : HIGH" in report
    assert "AGENCY DRIFT         : LOW" in report
    assert "ESCAPE               : improbable" in report


def test_final_report_reads_low_confidence_for_an_unpredictable_player():
    report = final_report(hits=1, total=5, accuracy=0.2, dominant="defiance")
    assert "PREDICTABILITY INDEX : 20%" in report
    assert "MODEL CONFIDENCE     : LOW" in report
    assert "AGENCY DRIFT         : HIGH" in report
    assert "ESCAPE               : open" in report
    assert "harder to predict" in report


def test_final_report_has_a_moderate_middle_band():
    report = final_report(hits=2, total=4, accuracy=0.5, dominant="control")
    assert "MODEL CONFIDENCE     : MODERATE" in report
    assert "AGENCY DRIFT         : ELEVATED" in report
    assert "ESCAPE               : plausible" in report
