"""Tests that pin down the one fully worked example — the acceptance artifact.

These assert the worked loop actually demonstrates, end to end:
``scene -> choices -> state update -> visible "Mirror noticed..." reason``,
the single adaptation type changing the next scene, and compatibility with the
locked acceptance gate's decision-point shape.
"""

from __future__ import annotations

from loop.example import (
    THRESHOLD,
    WORKED_SESSION,
    run_worked_example,
    to_session_log,
    transcript,
)


def test_worked_example_reflects_exactly_once_on_turn_three():
    played = run_worked_example()
    reflections = [p.result.reflection for p in played]
    fired = [(i, r) for i, r in enumerate(reflections, start=1) if r is not None]
    assert len(fired) == 1, "the Mirror should notice exactly once"
    turn, reflection = fired[0]
    assert turn == 3
    assert reflection.tendency == "kindness"
    assert reflection.count == 3
    assert reflection.total == 3


def test_worked_example_reason_cites_only_in_game_evidence():
    played = run_worked_example()
    reflection = next(p.result.reflection for p in played if p.result.reflection)
    rendered = reflection.render()
    assert rendered.startswith("Mirror noticed")
    # the three cited reasons are the evidence phrases from the kind choices made
    expected = [
        "reassured the technician at intake",
        "left another participant's file closed",
        "guided a disoriented participant to safety",
    ]
    assert list(reflection.evidence) == expected
    for ev in expected:
        assert ev in rendered


def test_single_adaptation_surfaces_predicted_choice_in_final_scene():
    played = run_worked_example()
    final = played[-1]
    # THRESHOLD declares kindness ("c_wait") last; the Mirror must move it first.
    assert THRESHOLD.choices[-1].id == "c_wait"
    assert final.offered.choices[0].id == "c_wait"
    assert final.result.predicted_actions[0] == "c_wait"


def test_transcript_shows_all_four_stages():
    text = transcript()
    assert "SCENE" in text
    assert "CHOICES" in text
    assert "STATE UPDATE" in text
    assert "Mirror noticed" in text
    assert "ADAPTATION" in text  # the single adaptation type, made visible


def test_worked_example_emits_gate_compatible_decision_points():
    # The loop's output feeds the locked acceptance gate without translation.
    from acceptance.predictability import DecisionPoint, evaluate

    log = to_session_log(run_worked_example())
    assert len(log["decision_points"]) == len(WORKED_SESSION)

    points = [
        DecisionPoint(
            predicted_actions=tuple(dp["predicted_actions"]),
            actual_action=dp["actual_action"],
        )
        for dp in log["decision_points"]
    ]
    result = evaluate(points)
    # A 4-turn demo is intentionally too short to be *scored* (the gate needs a
    # full session); the point is that the shapes line up and it evaluates.
    assert result.n == len(WORKED_SESSION)
    assert "insufficient data" in result.reason
