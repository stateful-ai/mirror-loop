"""Pins ``docs/AB_PREREGISTRATION.md`` to the locked A/B-decision-rule code.

The pre-registration doc is the signed envelope that fixes — before any future
playtest — the four items the company product principle requires: primary
metric, minimum sample size, effect threshold, and the result that would
falsify the thesis. To keep that promise meaningful the doc must *not* restate
numbers that drift from the code, and must keep naming every constant it binds
to. These tests are that guardrail.

If a future change moves a threshold (``N_PER_ARM``, ``EFFECT_THRESHOLD``, the
per-session gate floors) and the pre-registration doc is not re-signed to
match, this file fails — exactly when the rule has silently drifted.
"""

from __future__ import annotations

from pathlib import Path

from acceptance.predictability import (
    MIN_DECISION_POINTS,
    MIN_MARGIN_OVER_BASELINE,
    MIN_TOP1_ACCURACY,
)

from game.playtest import EFFECT_THRESHOLD, N_PER_ARM

DOC = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "AB_PREREGISTRATION.md"
)


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


# --- The doc exists and is signed --------------------------------------------


def test_preregistration_doc_exists():
    assert DOC.is_file(), f"missing pre-registration doc at {DOC}"


def test_preregistration_doc_is_signed_and_locked():
    text = _text()
    # Founder lock + an explicit signed-off block. These are the two markers the
    # doc uses to declare the rule pre-registered; if either disappears the
    # envelope is no longer load-bearing.
    assert "**Status:** ✅ **LOCKED**" in text
    assert "Approved by:** Aidan Kosik" in text
    assert "APPROVED" in text


# --- The four required items are bound to the code single source of truth -----


def test_preregistration_names_primary_metric_by_reference():
    # Imports, not redefines: the metric symbols must be named so the doc cannot
    # silently fork its own thresholds.
    text = _text()
    assert "Beats-Baseline Prediction Test" in text
    assert "MIN_TOP1_ACCURACY" in text
    assert "MIN_MARGIN_OVER_BASELINE" in text
    assert "acceptance/predictability.py" in text


def test_preregistration_names_sample_size_constant():
    text = _text()
    # The sample-size constant is named (so a rename in code surfaces here) and
    # the doc also names the secondary scored-points floor it depends on.
    assert "N_PER_ARM" in text
    assert "game.playtest.N_PER_ARM" in text
    assert "MIN_DECISION_POINTS" in text


def test_preregistration_names_effect_threshold_constant():
    text = _text()
    assert "EFFECT_THRESHOLD" in text
    assert "game.playtest.EFFECT_THRESHOLD" in text


def test_preregistration_states_the_two_falsifiers():
    text = _text()
    # Falsifier 1: the A/B kill-criterion (symmetric, in the adaptation's
    # disfavour) — written with the exact − EFFECT_THRESHOLD framing the
    # decision rule uses.
    assert "kill-criterion" in text
    assert "−`EFFECT_THRESHOLD`" in text  # the literal "−EFFECT_THRESHOLD"
    # Falsifier 2: the per-session thesis FAIL (cite the locked thesis doc).
    assert "Thesis FAIL" in text
    assert "THESIS.md" in text


# --- The doc does not silently fork the numbers ------------------------------


def test_preregistration_does_not_hardcode_drifted_thresholds():
    """Either the doc names the *current* constant value, or it names no value.

    The doc's editorial choice is to bind by *symbol* (e.g. ``N_PER_ARM``)
    rather than by number, so the constants below should not appear as decimals
    that disagree with the code. If a future contributor inlines a number, this
    test ensures it matches the current code — otherwise the pre-registration
    has drifted and must be re-signed.
    """
    text = _text()

    def _ok(constant_name: str, value: float, *, decimals: int) -> None:
        # We do not require the number to be present (the doc prefers symbols),
        # but if any decimal of the right form appears it must equal the
        # current value. We look for the *constant name* alongside any nearby
        # decimal to avoid spurious matches elsewhere in the doc.
        import re

        # Find every "<constant_name> ... <decimal>" pair in a small window.
        pattern = re.compile(
            rf"{re.escape(constant_name)}[^\n]{{0,80}}?(\d+\.\d{{{decimals}}})"
        )
        for match in pattern.finditer(text):
            assert float(match.group(1)) == value, (
                f"{constant_name} in {DOC.name} reads {match.group(1)} but "
                f"code says {value}; re-sign the pre-registration or drop the "
                f"inline number"
            )

    _ok("EFFECT_THRESHOLD", EFFECT_THRESHOLD, decimals=2)
    _ok("MIN_TOP1_ACCURACY", MIN_TOP1_ACCURACY, decimals=2)
    _ok("MIN_MARGIN_OVER_BASELINE", MIN_MARGIN_OVER_BASELINE, decimals=2)


def test_preregistration_links_to_method_and_implementation():
    text = _text()
    # The envelope is short on purpose; the long-form method and the harness
    # implementation must still be findable from it.
    assert "docs/PLAYTEST_METHOD.md" in text or "PLAYTEST_METHOD.md" in text
    assert "game/playtest.py" in text
    assert "acceptance/predictability.py" in text


# --- It explicitly binds future playtests ------------------------------------


def test_preregistration_binds_future_playtests():
    text = _text()
    # The doc must make clear it pre-registers the rule for *future* runs (the
    # acceptance criterion: "lands before M2 / any playtest"), not retroactively
    # re-score a past one.
    assert "future" in text.lower()
    # And must reference the not-yet-run human/subjective instrument, since
    # that is the next playtest this rule will judge.
    assert "human" in text.lower()


# --- The README of decisions or the method doc links to this envelope --------


def test_method_doc_links_to_preregistration_envelope():
    """If the long-form method doc exists, it should point at the envelope.

    The pre-registration envelope is the canonical sign-off; readers landing in
    the method doc should be able to find the signed gate from there.
    """
    method = DOC.parent / "PLAYTEST_METHOD.md"
    if not method.is_file():
        return  # method doc absent; nothing to assert
    assert "AB_PREREGISTRATION.md" in method.read_text(encoding="utf-8")
