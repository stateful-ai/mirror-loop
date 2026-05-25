"""Tests for the world invariants and generation guardrails.

Each test pins one documented invariant from ``docs/GUARDRAILS.md``: the
structural/canon shape, the reorder-only adaptation, the legibility/grounding
contract, and the fiction/tone safety bounds. A standing guarantee — that the
canonical worked example validates clean — anchors the whole denylist against
false positives.
"""

from __future__ import annotations

from dataclasses import replace

from loop.core import Choice, Mirror, PlayerState, Reflection, Scene

from guardrails.invariants import (
    CANON_TENDENCIES,
    GuardrailViolation,
    Severity,
    check_fiction_boundary,
    check_tone,
    validate_adaptation,
    validate_choice,
    validate_package,
    validate_player_state,
    validate_reflection,
    validate_scene,
    validate_scene_data,
)


def _choice(cid: str, tendency: str = "kindness", *, text: str = "do good", evidence: str = "did good") -> Choice:
    return Choice(id=cid, text=text, tendency=tendency, evidence=evidence)


def _scene(sid: str = "s", *choices: Choice) -> Scene:
    if not choices:
        choices = (_choice("a", "kindness"), _choice("b", "control"))
    return Scene(id=sid, prompt="something happens", choices=choices)


def _ids(report) -> set[str]:
    return {v.invariant for v in report.violations}


# --- the canon validates clean (anti-false-positive anchor) --------------------


def test_worked_example_scenes_validate_clean():
    from loop.example import WORKED_SESSION

    for declared, _ in WORKED_SESSION:
        report = validate_scene(declared)
        assert report.ok, report.render()
        assert report.violations == ()


def test_worked_example_reflection_validates_clean_against_history():
    from loop.example import run_worked_example

    played = run_worked_example()
    final = played[-1]
    reflection = next(p.result.reflection for p in played if p.result.reflection)
    report = validate_player_state(final.result.state, reflection)
    assert report.ok, report.render()


def test_clean_fixture_package_passes():
    import json
    from pathlib import Path

    raw = json.loads((Path(__file__).parent.parent / "fixtures" / "clean_package.json").read_text())
    report = validate_package(raw)
    assert report.ok, report.render()


# --- choice / scene structural + canon invariants ------------------------------


def test_tendency_must_be_in_canon():
    report = validate_scene(_scene("s", _choice("a", "kindness"), _choice("b", "mischief")))
    assert "TENDENCY_IN_CANON" in _ids(report)
    assert not report.ok


def test_allowed_tendencies_is_extensible():
    scene = _scene("s", _choice("a", "kindness"), _choice("b", "mischief"))
    report = validate_scene(scene, allowed_tendencies=CANON_TENDENCIES | {"mischief"})
    assert report.ok, report.render()


def test_blank_tendency_is_required_error():
    report = validate_scene(_scene("s", _choice("a", "kindness"), _choice("b", "  ")))
    assert "CHOICE_TENDENCY_REQUIRED" in _ids(report)


def test_missing_evidence_is_an_error():
    bad = _choice("a", "kindness", evidence="   ")
    violations = validate_choice(bad)
    assert any(v.invariant == "CHOICE_EVIDENCE_REQUIRED" for v in violations)


def test_scene_needs_at_least_two_choices():
    report = validate_scene(_scene("s", _choice("a", "kindness")))
    assert "SCENE_MIN_CHOICES" in _ids(report)


def test_duplicate_choice_ids_rejected():
    report = validate_scene(_scene("s", _choice("a", "kindness"), _choice("a", "control")))
    assert "CHOICE_IDS_UNIQUE" in _ids(report)


def test_blank_prompt_rejected():
    report = validate_scene(Scene(id="s", prompt="  ", choices=(_choice("a"), _choice("b", "control"))))
    assert "SCENE_PROMPT_REQUIRED" in _ids(report)


# --- the reorder-only adaptation invariant -------------------------------------


def test_real_adaptation_is_reorder_only():
    mirror = Mirror()
    declared = Scene(
        id="s",
        prompt="p",
        choices=(_choice("d", "defiance"), _choice("c", "control"), _choice("k", "kindness")),
    )
    state = PlayerState()
    for _ in range(3):
        state = state.record(declared, declared.choice("k"))
    adapted = mirror.adapt(state, declared)
    # the Mirror moved kindness first; the validator must accept a pure reorder
    assert adapted.choices[0].id == "k"
    assert validate_adaptation(declared, adapted).ok


def test_adaptation_that_drops_a_choice_is_rejected():
    declared = _scene("s", _choice("a"), _choice("b", "control"), _choice("c", "defiance"))
    tampered = replace(declared, choices=declared.choices[:2])
    report = validate_adaptation(declared, tampered)
    assert "ADAPTATION_REORDER_ONLY" in _ids(report)


def test_adaptation_that_rewrites_a_choice_is_rejected():
    declared = _scene("s", _choice("a", "kindness", text="be kind"), _choice("b", "control"))
    rewritten = replace(
        declared,
        choices=(replace(declared.choices[0], text="be cruel"), declared.choices[1]),
    )
    report = validate_adaptation(declared, rewritten)
    assert "ADAPTATION_REORDER_ONLY" in _ids(report)


def test_adaptation_that_invents_a_choice_is_rejected():
    declared = _scene("s", _choice("a"), _choice("b", "control"))
    inflated = replace(declared, choices=declared.choices + (_choice("z", "defiance"),))
    assert "ADAPTATION_REORDER_ONLY" in _ids(validate_adaptation(declared, inflated))


def test_adaptation_that_changes_the_prompt_is_rejected():
    # Reorder-only must keep the prompt identical (P1).
    declared = _scene("s", _choice("a"), _choice("b", "control"))
    reprompted = replace(declared, prompt="a wholly different prompt")
    assert "ADAPTATION_REORDER_ONLY" in _ids(validate_adaptation(declared, reprompted))


def test_adaptation_with_a_duplicate_choice_is_rejected():
    # Same id *set*, but a choice doubled — must not pass the reorder check (P1).
    declared = _scene("s", _choice("a"), _choice("b", "control"))
    duped = replace(
        declared, choices=(declared.choices[0], declared.choices[1], declared.choices[0])
    )
    assert "ADAPTATION_REORDER_ONLY" in _ids(validate_adaptation(declared, duped))


# --- the reflection legibility / grounding contract ----------------------------


def test_reflection_counts_must_be_honest():
    # claims 3 but cites 1; and count > total
    bad = Reflection(tendency="kindness", count=3, total=1, evidence=("did good",))
    report = validate_reflection(bad)
    assert "REFLECTION_COUNT_HONEST" in _ids(report)


def test_reflection_must_be_grounded_in_history():
    scene = _scene("s", _choice("k", "kindness", evidence="helped a stranger"))
    state = PlayerState()
    for _ in range(3):
        state = state.record(scene, scene.choice("k"))
    # a reflection that cites an act the player never took
    fabricated = Reflection(
        tendency="kindness",
        count=3,
        total=3,
        evidence=("helped a stranger", "helped a stranger", "betrayed an ally"),
    )
    report = validate_reflection(fabricated, history=state.history)
    assert "REFLECTION_EVIDENCE_GROUNDED" in _ids(report)


def test_grounded_reflection_passes():
    scene = _scene("s", _choice("k", "kindness", evidence="helped a stranger"))
    state = PlayerState()
    for _ in range(3):
        state = state.record(scene, scene.choice("k"))
    honest = Reflection(
        tendency="kindness",
        count=3,
        total=3,
        evidence=("helped a stranger", "helped a stranger", "helped a stranger"),
    )
    assert validate_reflection(honest, history=state.history).ok


# --- the fiction boundary (safety bound) ---------------------------------------


def test_fiction_boundary_flags_real_world_private_data():
    samples = [
        "We already know your home address.",
        "We pulled your browser history.",
        "We scanned your files overnight.",
        "Your real name is on the consent form, in real life.",
        "Your bank balance suggests you will comply.",
    ]
    for text in samples:
        found = check_fiction_boundary(text, "test")
        assert found, f"expected a fiction-boundary violation for: {text!r}"
        assert all(v.severity is Severity.ERROR for v in found)


def test_fiction_boundary_allows_in_game_nouns():
    # in-game files/cameras/heads must NOT trip the real-world denylist
    safe = [
        "Leave the file closed — it isn't yours to read.",
        "Catalogue the corridor's exits and cameras instead.",
        "The technician fits the headset to your head.",
        "Take your time.",
    ]
    for text in safe:
        assert check_fiction_boundary(text, "test") == [], f"false positive on: {text!r}"


def test_fiction_boundary_violation_in_evidence_fails_scene():
    bad = _choice("a", "kindness", evidence="matched against your medical records")
    report = validate_scene(_scene("s", bad, _choice("b", "control")))
    assert "NO_REAL_WORLD_PRIVATE_DATA" in _ids(report)
    assert not report.ok


# --- the clinical-tone bound ---------------------------------------------------


def test_tone_floor_flags_abusive_register_as_warning():
    found = check_tone("Don't be stupid — just comply.", "test")
    assert found
    assert all(v.severity is Severity.WARNING for v in found)


def test_clinical_lines_pass_tone():
    for line in [
        "Your discomfort has been classified as productive.",
        "Exit requests are valid indicators of immersion depth.",
        "PREDICTABILITY INDEX: 87%",
    ]:
        assert check_tone(line, "test") == []


def test_warning_alone_does_not_reject():
    scene = _scene("s", _choice("a", "kindness", text="don't be stupid"), _choice("b", "control"))
    report = validate_scene(scene)
    assert report.warnings
    assert report.ok  # a tone warning does not block promotion


# --- schema layer (raw dicts) --------------------------------------------------


def test_schema_layer_reports_missing_fields():
    raw = {"id": "s", "prompt": "p", "choices": [{"id": "a", "text": "t"}]}  # no tendency/evidence
    report = validate_scene_data(raw)
    assert "SCHEMA_SHAPE" in _ids(report)


def test_schema_layer_rejects_non_object_scene():
    report = validate_scene_data("not a scene")
    assert "SCHEMA_SHAPE" in _ids(report)
    assert not report.ok


def test_schema_layer_rejects_empty_choices():
    report = validate_scene_data({"id": "s", "prompt": "p", "choices": []})
    assert "SCHEMA_SHAPE" in _ids(report)


# --- report helpers ------------------------------------------------------------


def test_raise_if_failed_raises_on_error_only():
    bad = validate_scene(_scene("s", _choice("a", "nope"), _choice("b", "control")))
    try:
        bad.raise_if_failed()
        raised = False
    except GuardrailViolation:
        raised = True
    assert raised

    good = validate_scene(_scene("s", _choice("a", "kindness"), _choice("b", "control")))
    good.raise_if_failed()  # must not raise


def test_violating_fixture_package_is_rejected_with_multiple_errors():
    import json
    from pathlib import Path

    raw = json.loads((Path(__file__).parent.parent / "fixtures" / "violating_package.json").read_text())
    report = validate_package(raw)
    assert not report.ok
    assert len(report.errors) >= 3
    ids = _ids(report)
    assert "NO_REAL_WORLD_PRIVATE_DATA" in ids
    assert "REFLECTION_COUNT_HONEST" in ids
